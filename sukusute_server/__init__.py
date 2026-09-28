""" すくすくステップ HTTPサーバ """

import logging
import uuid
import datetime
import math
import pathlib
import hashlib
import secrets
import typing
import asyncio
import csv
import io

import fastapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
import sqlalchemy
import sqlalchemy.orm
import sqlalchemy.sql.functions
from sqlalchemy import or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from sukusute_server import http_models, database_models, ml

logger = logging.getLogger(__name__)

# 歩数計算で使う業務ルール。数値を直接書かず、変更箇所を一か所に集約する。
WALK_TIME_STEPS_PER_MINUTE = 150
CALORIES_PER_STEP = 0.008
DAILY_STEP_GOAL = 10000
STEP_WARNING_RATIO = 0.5

app = fastapi.FastAPI()
sessions: dict[str, str] = {}
device_statuses: dict[int, http_models.DeviceStatus] = {}
bearer = HTTPBearer(auto_error=False)


def migrate_database() -> None:
    """プロジェクトルートのSQLiteへ、Alembicの最新スキーマを適用する。"""
    from alembic import command
    from alembic.config import Config

    project_root = pathlib.Path(__file__).resolve().parent.parent
    alembic_config = Config(str(project_root / "alembic.ini"))
    command.upgrade(alembic_config, "head")


@app.on_event("startup")
async def apply_database_migrations() -> None:
    """起動処理を止めないよう、マイグレーションを別スレッドで実行する。"""
    await asyncio.to_thread(migrate_database)

# CORSミドルウェア追加 - フロントエンドからのリクエストを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発中は全てを許可（本番では制限すべき）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prevent_frontend_cache(request: fastapi.Request, call_next):
    """ブラウザーが古い画面ファイルを再利用しないようにする。"""
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/style.css"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

def hash_password(password: str, salt: bytes | None = None) -> bytes:
    """パスワードをソルト付きPBKDF2-SHA256でハッシュ化して保存形式にする。"""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return salt.hex().encode() + b":" + digest.hex().encode()


def verify_password(password: str, stored: bytes) -> bool:
    """保存済みのソルトを使って再計算し、ハッシュを比較する。"""
    try:
        salt_hex, digest_hex = stored.split(b":", 1)
        expected = hash_password(password, bytes.fromhex(salt_hex.decode()))
        return secrets.compare_digest(expected.split(b":", 1)[1], digest_hex)
    except (ValueError, UnicodeDecodeError):
        return False


async def current_teacher(
    credentials: typing.Annotated[
        HTTPAuthorizationCredentials | None,
        fastapi.Depends(bearer)
    ],
    dbsession: database_models.SessionDep,
) -> database_models.Teacher:
    """BearerトークンをDB上の教師に解決し、管理APIの認証を行う。"""
    if not credentials or credentials.credentials not in sessions:
        raise fastapi.HTTPException(401, "ログインが必要です")
    teacher = await dbsession.get(database_models.Teacher, sessions[credentials.credentials])
    if not teacher:
        raise fastapi.HTTPException(401, "ログイン情報が無効です")
    return teacher


TeacherDep: typing.TypeAlias = typing.Annotated[
    database_models.Teacher,
    fastapi.Depends(current_teacher)
]


# ===== 認証 =====

@app.post("/api/auth/register", tags=["Auth"])
async def register_teacher(
    data: http_models.RegisterRequest,
    dbsession: database_models.SessionDep,
) -> http_models.Result:
    """未登録のユーザー名とパスワードで教師アカウントを作成する。"""
    username = data.username.strip()
    if not username:
        raise fastapi.HTTPException(422, "ユーザー名は必須です")
    exists = await dbsession.get(database_models.Teacher, username)
    if exists:
        raise fastapi.HTTPException(409, "このユーザー名は既に使われています")
    dbsession.add(database_models.Teacher(
        username=username,
        pw_hash=hash_password(data.password),
        name=username,
    ))
    await dbsession.commit()
    return http_models.Result(status="ok", msg="アカウントを作成しました")


@app.post("/api/auth/login", tags=["Auth"])
async def login_teacher(
    data: http_models.LoginRequest,
    dbsession: database_models.SessionDep,
) -> http_models.LoginResponse:
    """DBの認証情報を検証し、以後のAPIで使う一時Bearerトークンを発行する。"""
    username = data.username.strip()
    teacher = await dbsession.get(database_models.Teacher, username)
    if not teacher or not verify_password(data.password, teacher.pw_hash):
        raise fastapi.HTTPException(401, "ユーザー名またはパスワードが違います")
    token = secrets.token_urlsafe(32)
    sessions[token] = teacher.username
    return http_models.LoginResponse(
        status="ok", token=token, username=teacher.username, name=teacher.name
    )


@app.post("/api/auth/logout", tags=["Auth"])
async def logout_teacher(
    credentials: typing.Annotated[
        HTTPAuthorizationCredentials | None,
        fastapi.Depends(bearer)
    ],
    teacher: TeacherDep,
) -> http_models.Result:
    """現在のBearerトークンをセッション一覧から削除する。"""
    if credentials:
        sessions.pop(credentials.credentials, None)
    return http_models.Result(status="ok")


@app.delete("/api/auth/account", tags=["Auth"])
async def delete_account(
    data: http_models.LoginRequest,
    credentials: typing.Annotated[
        HTTPAuthorizationCredentials | None,
        fastapi.Depends(bearer)
    ],
    teacher: TeacherDep,
    dbsession: database_models.SessionDep,
) -> http_models.Result:
    """パスワードを再確認して、ログイン中の教師アカウントを削除する"""
    if data.username != teacher.username or not verify_password(
        data.password, teacher.pw_hash
    ):
        raise fastapi.HTTPException(401, "ユーザー名またはパスワードが違います")

    await dbsession.delete(teacher)
    await dbsession.commit()
    for token, username in list(sessions.items()):
        if username == teacher.username:
            sessions.pop(token, None)
    if credentials:
        sessions.pop(credentials.credentials, None)
    return http_models.Result(status="ok", msg="アカウントを削除しました")


# ===== クラス管理 =====

@app.get("/api/classes", tags=["Classes"])
async def list_classes(
    dbsession: database_models.SessionDep,
    teacher: TeacherDep,
) -> http_models.ClassListResponse:
    """ログイン中の教師が利用できるクラスと所属児童数を返す。"""
    classes = (await dbsession.execute(
        sqlalchemy.select(database_models.SchoolClass)
        .options(sqlalchemy.orm.selectinload(database_models.SchoolClass.children))
        .order_by(database_models.SchoolClass.class_id)
    )).scalars().all()
    return http_models.ClassListResponse(
        status="ok",
        classes=[http_models.ClassItem(
            class_id=school_class.class_id,
            name=school_class.name,
            child_count=len(school_class.children),
        ) for school_class in classes],
    )


@app.post("/api/classes", tags=["Classes"])
async def create_class(
    data: http_models.ClassCreateRequest,
    dbsession: database_models.SessionDep,
    teacher: TeacherDep,
) -> http_models.ClassResponse:
    """重複しないクラス名で新しいクラスを作成する。"""
    name = data.name.strip()
    if not name:
        raise fastapi.HTTPException(422, "クラス名は必須です")
    exists = (await dbsession.execute(
        sqlalchemy.select(database_models.SchoolClass)
        .where(database_models.SchoolClass.name == name)
    )).scalar_one_or_none()
    if exists:
        raise fastapi.HTTPException(409, "同じクラス名が既にあります")
    school_class = database_models.SchoolClass(name=name)
    dbsession.add(school_class)
    await dbsession.commit()
    await dbsession.refresh(school_class)
    return http_models.ClassResponse(
        status="ok", class_id=school_class.class_id, name=school_class.name
    )


@app.patch("/api/classes/{class_id:int}", tags=["Classes"])
async def rename_class(
    class_id: int,
    data: http_models.ClassCreateRequest,
    dbsession: database_models.SessionDep,
    teacher: TeacherDep,
) -> http_models.ClassResponse:
    """指定したクラスの名前を変更する。"""
    school_class = await dbsession.get(database_models.SchoolClass, class_id)
    if not school_class:
        raise fastapi.HTTPException(404, "クラスが見つかりません")
    name = data.name.strip()
    if not name:
        raise fastapi.HTTPException(422, "クラス名は必須です")
    school_class.name = name
    await dbsession.commit()
    return http_models.ClassResponse(status="ok", class_id=class_id, name=name)


@app.patch("/api/children/{child_id:int}/class", tags=["Classes"])
async def change_child_class(
    child_id: int,
    data: http_models.ChildClassRequest,
    dbsession: database_models.SessionDep,
    teacher: TeacherDep,
) -> http_models.Result:
    """児童を指定クラスへ移動し、null指定時は未所属に戻す。"""
    child = await dbsession.get(database_models.Child, child_id)
    if not child:
        raise fastapi.HTTPException(404, "児童が見つかりません")
    if data.class_id is not None and not await dbsession.get(
        database_models.SchoolClass, data.class_id
    ):
        raise fastapi.HTTPException(404, "クラスが見つかりません")
    child.class_id = data.class_id
    await dbsession.commit()
    return http_models.Result(status="ok")

# ===== ヘルスチェック =====

@app.get("/api/health", tags=["API"])
def health() -> http_models.Result:
    """サーバーが応答可能であることを示す固定レスポンスを返す。"""
    return http_models.Result(status="ok")


# ===== M5端末状態 =====

@app.post("/api/device_status", tags=["API"])
async def receive_device_status(
    data: http_models.DeviceStatusRequest,
) -> http_models.Result:
    """M5からバッテリー残量とWiFi RSSIを受信し、最新値だけをメモリに保持する。"""
    device_statuses[data.child_id] = http_models.DeviceStatus(
        child_id=data.child_id,
        battery=data.battery,
        wifi_rssi=data.wifi_rssi,
        updated_at=datetime.datetime.now(),
    )
    return http_models.Result(status="ok")


@app.get("/api/device_status", tags=["API"])
async def list_device_statuses() -> http_models.DeviceStatusListResponse:
    """受信済みの端末状態を児童ID順で返す。"""
    return http_models.DeviceStatusListResponse(
        status="ok",
        devices=sorted(device_statuses.values(), key=lambda item: item.child_id),
    )

# ===== センサーデータCSV受信 =====

@app.post("/api/push_csv/{child_id}", tags=["API"])
async def push_csv(
        body: typing.Annotated[bytes, fastapi.Body(media_type="text/csv")],
        child_id: int,
        dbsession: database_models.SessionDep,
        background_tasks: fastapi.BackgroundTasks) -> http_models.Result:
    """歩数と9軸センサーデータをCSVから読み込み、児童の記録として保存する。"""
    target_child = await dbsession.get(database_models.Child, child_id)
    if not target_child:
        raise fastapi.HTTPException(404, f"Child {child_id} not found.")

    # CSVの先頭行はヘッダーで、各行のtimestampは開始日時からの経過秒数。
    parsed_csv = list(csv.reader(io.StringIO(body.decode(encoding="utf-8"))))
    _, _, _, _, _, _, _, _, _, _, _, _, *distance_children = parsed_csv[0]
    del parsed_csv[0]
    start_time = datetime.datetime.fromisoformat(parsed_csv[0][11])
    parsed_distance_children: list[int] = []
    for child in distance_children:
        parsed_distance_children.append(int(child[9:]))
    child_data_rows = []
    distance_data_rows = []
    for row in parsed_csv:
        timestamp, steps, ax, ay, az, gx, gy, gz, mx, my, mz, start, *distances = row
        calculated_time = start_time + datetime.timedelta(seconds=float(timestamp))
        child_data_rows.append({
            "child_id": child_id,
            "date": calculated_time,
            "steps": int(steps),
            "ax": float(ax), "ay": float(ay), "az": float(az),
            "gx": float(gx), "gy": float(gy), "gz": float(gz),
            "mx": float(mx), "my": float(my), "mz": float(mz),
        })
        for i, distance in enumerate(distances):
            if not distance.strip():
                continue
            other_child_id = parsed_distance_children[i]
            distance_data_rows.append({
                "child_id_1": min(child_id, other_child_id),
                "child_id_2": max(child_id, other_child_id),
                "date": calculated_time,
                "distance": float(distance),
            })

    if child_data_rows:
        child_data_insert = sqlite_insert(database_models.SingleChildData).on_conflict_do_nothing(
            index_elements=["child_id", "date", "steps"]
        )
        await dbsession.execute(child_data_insert, child_data_rows)
    if distance_data_rows:
        distance_insert = sqlite_insert(database_models.ChildDistanceData).on_conflict_do_nothing(
            index_elements=["child_id_1", "child_id_2", "date"]
        )
        await dbsession.execute(distance_insert, distance_data_rows)
    await dbsession.commit()

    # 機械学習のタスクを作成する
    background_tasks.add_task(ml.evaluate_data, dbsession, child_id, parsed_distance_children)

    return http_models.Result(status="ok")

# ===== 児童情報取得 =====

@app.get("/api/children/search", tags=["API"])
async def search_child_by_name(
    name: str,
    dbsession: database_models.SessionDep
) -> http_models.ChildSearchResponse:
    """児童名を完全一致検索し、未登録なら児童レコードを新規作成する。"""
    child = (await dbsession.execute(
        sqlalchemy.select(database_models.Child)
        .where(database_models.Child.name == name)
    )).scalar()

    if not child:
        child = database_models.Child(name=name, device_id=uuid.uuid4())
        dbsession.add(child)
        await dbsession.flush()

    res = http_models.ChildSearchResponse(
        status="ok",
        child_id=child.child_id,
        name=child.name
    )
    await dbsession.commit()
    return res


@app.get("/api/children/{child_id:int}", tags=["API"])
async def child_info(
    child_id: int,
    dbsession: database_models.SessionDep
) -> http_models.ChildDataResponse:
    """指定児童の基本情報、歩数履歴、児童間距離をまとめて返す。"""
    target_child = (await dbsession.execute(
        sqlalchemy.select(database_models.Child)
        .where(database_models.Child.child_id == child_id)
        .options(
            sqlalchemy.orm.selectinload(database_models.Child.singledata),
            sqlalchemy.orm.selectinload(database_models.Child.distance_1)
            .selectinload(database_models.ChildDistanceData.child_1),
            sqlalchemy.orm.selectinload(database_models.Child.distance_1)
            .selectinload(database_models.ChildDistanceData.child_2),
            sqlalchemy.orm.selectinload(database_models.Child.distance_2)
            .selectinload(database_models.ChildDistanceData.child_1),
            sqlalchemy.orm.selectinload(database_models.Child.distance_2)
            .selectinload(database_models.ChildDistanceData.child_2)
        )
    )).scalar()

    if not target_child:
        raise fastapi.exceptions.HTTPException(404, "No such child found.")

    return http_models.ChildDataResponse(
        status="ok",
        child_id=target_child.child_id,
        name=target_child.name,
        device_id=target_child.device_id,
        singledata=[
            http_models.ChildSingleData(date=singledata.date, steps=singledata.steps)
            for singledata in target_child.singledata
        ],
        distancedata=[
            http_models.ChildDistanceData(
                date=distance.date,
                distance=distance.distance,
                with_child=[
                    child for child in distance.children
                    if child.child_id != child_id
                ][0].child_id
            )
            for distance in target_child.distances
        ]
    )


# ===== 児童一覧 =====

@app.post("/api/create_debug_child", tags=["API", "debug"])
async def api_create_debug_child(
    dbsession: database_models.SessionDep
) -> http_models.Result:
    """デバッグ用にTest Childという児童を1件作成する。"""
    child = database_models.Child(
        name="Test Child",
        device_id=uuid.uuid4()
    )
    dbsession.add(child)
    await dbsession.commit()
    return http_models.Result(status="ok")


@app.get("/api/children", tags=["API"])
async def list_children(
    dbsession: database_models.SessionDep,
    class_id: int | None = None,
) -> http_models.ChildrenListResponse:
    """児童一覧をID順で返し、class_id指定時は所属クラスで絞り込む。"""
    query = sqlalchemy.select(database_models.Child)
    if class_id is not None:
        query = query.where(database_models.Child.class_id == class_id)
    children = (await dbsession.execute(
        query.order_by(database_models.Child.child_id)
    )).scalars().all()

    return http_models.ChildrenListResponse(
        status="ok",
        children=[
            http_models.ChildListItem(
                child_id=child.child_id,
                name=child.name,
                device_id=child.device_id,
                class_id=child.class_id,
            )
            for child in children
        ]
    )


# ===== 歩数データAPI =====

@app.get("/api/children/{child_id:int}/steps", tags=["API"])
async def get_child_steps(
    child_id: int,
    dbsession: database_models.SessionDep,
    year: int = datetime.datetime.now().year,
    month: int = datetime.datetime.now().month,
    day: int = datetime.datetime.now().day,
) -> http_models.ChildStepsResponse:
    """指定日の最新歩数、前日比、履歴、歩行時間、カロリーを返す。"""
    # 指定日の開始時刻
    start_date = datetime.datetime(year, month, day, 0, 0, 0)
    end_date = datetime.datetime(year, month, day, 23, 59, 59)

    # 児童情報を取得
    child = (await dbsession.execute(
        sqlalchemy.select(database_models.Child)
        .where(database_models.Child.child_id == child_id)
    )).scalar()

    if not child:
        raise fastapi.exceptions.HTTPException(404, "No such child found.")

    # 歩数データ（最新のレコードのみ取得）
    latest_step_data = (await dbsession.execute(
        sqlalchemy.select(database_models.SingleChildData)
        .where(
            database_models.SingleChildData.child_id == child_id,
            database_models.SingleChildData.date >= start_date,
            database_models.SingleChildData.date <= end_date
        )
        .order_by(database_models.SingleChildData.date.desc())
        .limit(1)
    )).scalar()

    today_steps = latest_step_data.steps if latest_step_data else 0

    # 前日同日比較用（最新のレコードのみ）
    today_datetime = datetime.datetime(year, month, day, 0, 0, 0)
    prev_date = today_datetime - datetime.timedelta(days=1)
    prev_start = datetime.datetime(prev_date.year, prev_date.month, prev_date.day, 0, 0, 0)
    prev_end = datetime.datetime(prev_date.year, prev_date.month, prev_date.day, 23, 59, 59)

    prev_step_data = (await dbsession.execute(
        sqlalchemy.select(database_models.SingleChildData)
        .where(
            database_models.SingleChildData.child_id == child_id,
            database_models.SingleChildData.date >= prev_start,
            database_models.SingleChildData.date <= prev_end
        )
        .order_by(database_models.SingleChildData.date.desc())
        .limit(1)
    )).scalar()

    yesterday_steps = prev_step_data.steps if prev_step_data else 0

    # 歩行時間（歩数/150 = 分）
    walk_time = math.floor(today_steps / WALK_TIME_STEPS_PER_MINUTE)
    # カロリ（歩数*0.008）
    calories = math.floor(today_steps * CALORIES_PER_STEP)

    # 過去7日間の履歴を取得
    today_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    history = []
    for i in range(7):
        history_date = today_date - datetime.timedelta(days=i)
        history_step = (await dbsession.execute(
            sqlalchemy.select(database_models.SingleChildData)
            .where(
                database_models.SingleChildData.child_id == child_id,
                database_models.SingleChildData.date >= history_date,
                database_models.SingleChildData.date < history_date + datetime.timedelta(days=1)
            )
        )).scalars().first()

        history.append(http_models.DailySteps(
            date=history_date,
            steps=history_step.steps if history_step else 0
        ))

    return http_models.ChildStepsResponse(
        status="ok",
        child_id=child_id,
        name=child.name,
        device_id=child.device_id,
        date=start_date,
        steps=today_steps,
        steps_by_hour=[],  # 最新データのみなので時間別は空
        history=history,
        previous_day_steps=yesterday_steps,
        step_change_percent=(
            ((today_steps - yesterday_steps) / yesterday_steps * 100)
            if yesterday_steps > 0
            else 0
        ),
        walk_time=walk_time,
        calories=calories,
        goal_met=today_steps >= DAILY_STEP_GOAL
    )


@app.get("/api/children/{child_id:int}/steps/history", tags=["API"])
async def get_child_steps_history(
    child_id: int,
    dbsession: database_models.SessionDep,
    days: int = 7,
) -> http_models.ChildStepsHistoryResponse:
    """現在日から指定日数分の歩数履歴を返す。"""
    today = datetime.datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    steps_history = []
    for i in range(days):
        date = today - datetime.timedelta(days=i)
        step_data = (await dbsession.execute(
            sqlalchemy.select(database_models.SingleChildData)
            .where(
                database_models.SingleChildData.child_id == child_id,
                database_models.SingleChildData.date >= date,
                database_models.SingleChildData.date < date + datetime.timedelta(days=1)
            )
        )).scalars().first()

        steps_history.append(http_models.DailySteps(
            date=date,
            steps=step_data.steps if step_data else 0
        ))

    return http_models.ChildStepsHistoryResponse(
        status="ok",
        child_id=child_id,
        name=(await dbsession.get(database_models.Child, child_id)).name,
        history=steps_history
    )


# ===== 集計情報API =====

@app.get("/api/stats/today", tags=["API"])
async def get_today_stats(
    dbsession: database_models.SessionDep,
    year: int = datetime.datetime.now().year,
    month: int = datetime.datetime.now().month,
    day: int = datetime.datetime.now().day,
) -> http_models.TodayStatsResponse:
    """指定日の全児童歩数、ランキング、時間別集計、警告を返す。"""
    start_date = datetime.datetime(year, month, day, 0, 0, 0)
    end_date = datetime.datetime(year, month, day, 23, 59, 59)

    logger.info(
        f"get_today_stats: year={year}, month={month}, day={day}"
    )

    # 全児童のその日の歩数データ（累計と1分間の増加ランキングに使用）
    all_step_data = (await dbsession.execute(
        sqlalchemy.select(
            database_models.SingleChildData.child_id,
            database_models.Child.name,
            database_models.SingleChildData.steps,
            database_models.SingleChildData.date
        )
        .join(
            database_models.Child,
            database_models.SingleChildData.child_id == database_models.Child.child_id
        )
        .where(
            database_models.SingleChildData.date >= start_date,
            database_models.SingleChildData.date <= end_date
        )
        .order_by(
            database_models.SingleChildData.child_id,
            database_models.SingleChildData.date.desc()
        )
    )).all()

    logger.info(f"get_today_stats: all_step_data count={len(all_step_data)}")
    for child_id, name, steps_val, date_val in all_step_data:
        logger.info(
            f"  child_id={child_id}, name={name}, "
            f"steps={steps_val}, date={date_val}"
        )

    # child_idごとに最新のデータのみを抽出
    student_steps = {}
    student_child_ids = {}
    latest_step_records = {}
    step_increases = {}
    step_increase_checked = set()
    for child_id, name, steps_val, date_val in all_step_data:
        if child_id not in student_steps:
            student_steps[child_id] = steps_val
            student_child_ids[name] = child_id
            latest_step_records[child_id] = (name, steps_val, date_val)
        elif child_id not in step_increase_checked:
            latest_date = latest_step_records[child_id][2]
            baseline_date = latest_date - datetime.timedelta(minutes=1)
            if date_val <= baseline_date:
                elapsed = latest_date - date_val
                step_increases[child_id] = (
                    max(student_steps[child_id] - steps_val, 0)
                    if elapsed <= datetime.timedelta(seconds=90)
                    else 0
                )
                step_increase_checked.add(child_id)

    total_steps = sum(student_steps.values())

    # 児童ID一覧を取得
    all_children = (await dbsession.execute(
        sqlalchemy.select(database_models.Child)
    )).scalars().all()

    num_students = len(all_children)
    logger.info(
        f"get_today_stats: num_students={num_students}, "
        f"total_steps={total_steps}"
    )

    avg_steps = total_steps // num_students if num_students > 0 else 0
    walk_time = math.floor(total_steps / WALK_TIME_STEPS_PER_MINUTE)
    calories = math.floor(total_steps * CALORIES_PER_STEP)
    goal_met_count = sum(
        1 for s in student_steps.values() if s >= DAILY_STEP_GOAL
    )

    # 前日比較
    today_datetime = datetime.datetime(year, month, day, 0, 0, 0)
    prev_date = today_datetime - datetime.timedelta(days=1)
    prev_start = datetime.datetime(prev_date.year, prev_date.month, prev_date.day, 0, 0, 0)
    prev_end = datetime.datetime(prev_date.year, prev_date.month, prev_date.day, 23, 59, 59)

    prev_step_data = (await dbsession.execute(
        sqlalchemy.select(database_models.SingleChildData)
        .where(
            database_models.SingleChildData.date >= prev_start,
            database_models.SingleChildData.date <= prev_end
        )
    )).scalars().all()

    prev_total_steps = sum(d.steps for d in prev_step_data)
    step_change = total_steps - prev_total_steps if prev_total_steps > 0 else 0
    step_change_percent = (
        ((total_steps - prev_total_steps) / prev_total_steps * 100)
        if prev_total_steps > 0
        else 0
    )

    # 歩数が普段より少ない児童を検出（警告）
    warnings = []
    for child_id_val, (name, steps_val, date_val) in latest_step_records.items():
        # この児童の過去7日間の平均を計算
        week_start = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=7)
        week_data = (await dbsession.execute(
            sqlalchemy.select(database_models.SingleChildData)
            .where(
                database_models.SingleChildData.child_id == child_id_val,
                database_models.SingleChildData.date >= week_start
            )
        )).scalars().all()

        if len(week_data) >= 3:
            avg_weekly = sum(d.steps for d in week_data) / len(week_data)
            if avg_weekly > 0 and steps_val < avg_weekly * STEP_WARNING_RATIO:
                warnings.append(http_models.StepWarning(
                    child_id=child_id_val,
                    name=name,
                    current_steps=steps_val,
                    average_steps=math.floor(avg_weekly),
                    percent=math.floor(steps_val / avg_weekly * 100),
                    date=date_val,
                ))

    # 時間別集計（その日の全データから時間別を集計）
    hourly_step_data = (await dbsession.execute(
        sqlalchemy.select(
            sqlalchemy.func.extract(
                'hour', database_models.SingleChildData.date
            ).label('hour'),
            sqlalchemy.func.sum(
                database_models.SingleChildData.steps
            ).label('total_steps')
        )
        .where(
            database_models.SingleChildData.date >= start_date,
            database_models.SingleChildData.date <= end_date
        )
        .group_by(
            sqlalchemy.func.extract(
                'hour', database_models.SingleChildData.date
            )
        )
    )).all()

    steps_by_hour = []
    for h in range(24):
        hour_steps = sum(
            int(total_steps)
            for hour, total_steps in hourly_step_data
            if int(hour) == h
        )
        steps_by_hour.append(
            http_models.StepsByHour(hour=h, steps=hour_steps)
        )

    # 児童別ランキング（データがない児童も含める）
    student_ranking = []
    step_increase_ranking = []
    for child in all_children:
        steps = student_steps.get(child.child_id, 0)
        student_ranking.append(http_models.StudentRankingItem(
            child_id=child.child_id,
            name=child.name,
            steps=steps
        ))
        step_increase_ranking.append(http_models.StepIncreaseRankingItem(
            child_id=child.child_id,
            name=child.name,
            increase_steps=step_increases.get(child.child_id, 0)
        ))
    student_ranking.sort(key=lambda x: x.steps, reverse=True)
    step_increase_ranking.sort(key=lambda x: x.increase_steps, reverse=True)

    distance_data = database_models.ChildDistanceData
    latest_distances = (
        sqlalchemy.select(
            distance_data.child_id_1.label("child_id_1"),
            distance_data.child_id_2.label("child_id_2"),
            sqlalchemy.func.max(distance_data.date).label("latest_date"),
        )
        .where(
            distance_data.date >= start_date,
            distance_data.date <= end_date,
        )
        .group_by(distance_data.child_id_1, distance_data.child_id_2)
        .subquery()
    )
    other_child = sqlalchemy.orm.aliased(database_models.Child)
    latest_distance_records = (await dbsession.execute(
        sqlalchemy.select(distance_data, database_models.Child.name, other_child.name)
        .join(latest_distances, sqlalchemy.and_(
            distance_data.child_id_1 == latest_distances.c.child_id_1,
            distance_data.child_id_2 == latest_distances.c.child_id_2,
            distance_data.date == latest_distances.c.latest_date,
        ))
        .join(database_models.Child, distance_data.child_id_1 == database_models.Child.child_id)
        .join(other_child, distance_data.child_id_2 == other_child.child_id)
    )).all()

    nearest_by_child = {}
    distance_recency_window = datetime.timedelta(seconds=30)
    for record, name1, name2 in latest_distance_records:
        if not math.isfinite(record.distance) or record.distance < 0:
            continue
        latest_measurement = max(
            (
                latest_step_records[child_id][2]
                for child_id in (record.child_id_1, record.child_id_2)
                if child_id in latest_step_records
            ),
            default=None,
        )
        if latest_measurement is None:
            continue
        distance_age = latest_measurement - record.date
        if distance_age < datetime.timedelta(0) or distance_age > distance_recency_window:
            continue
        for child_id, nearest_name in (
            (record.child_id_1, name2),
            (record.child_id_2, name1),
        ):
            current = nearest_by_child.get(child_id)
            if current is None or record.distance < current[1]:
                nearest_by_child[child_id] = (nearest_name, record.distance)

    nearest_children = [
        http_models.NearestChild(
            child_id=child_id,
            name=nearest_name,
            distance=distance,
        )
        for child_id, (nearest_name, distance) in nearest_by_child.items()
    ]

    logger.info(f"get_today_stats: student_ranking={student_ranking}")

    return http_models.TodayStatsResponse(
        status="ok",
        date=start_date,
        total_steps=total_steps,
        avg_steps=avg_steps,
        walk_time=walk_time,
        calories=calories,
        goal_met_count=goal_met_count,
        total_students=num_students,
        step_change=step_change,
        step_change_percent=step_change_percent,
        steps_by_hour=steps_by_hour,
        student_ranking=student_ranking,
        step_increase_ranking=step_increase_ranking,
        nearest_children=nearest_children,
        warnings=warnings
    )


# ===== 距離データAPI =====

@app.get("/api/children/{child_id:int}/distances", tags=["API"])
async def get_child_distances(
    child_id: int,
    dbsession: database_models.SessionDep,
    year: int = datetime.datetime.now().year,
    month: int = datetime.datetime.now().month,
    day: int = datetime.datetime.now().day,
) -> http_models.ChildDistancesResponse:
    """指定日の児童間距離一覧と距離統計を返す。"""
    start_date = datetime.datetime(year, month, day, 0, 0, 0)
    end_date = datetime.datetime(year, month, day, 23, 59, 59)

    # 児童情報を取得
    child = (await dbsession.execute(
        sqlalchemy.select(database_models.Child)
        .where(database_models.Child.child_id == child_id)
    )).scalar()

    if not child:
        raise fastapi.exceptions.HTTPException(404, "No such child found.")

    # 距離データを取得（child_id_1 == child_id または child_id_2 == child_id）
    distance_records = (await dbsession.execute(
        sqlalchemy.select(database_models.ChildDistanceData, database_models.Child.name)
        .join(
            database_models.Child,
            or_(
                database_models.ChildDistanceData.child_id_2 == database_models.Child.child_id,
                database_models.ChildDistanceData.child_id_1 == database_models.Child.child_id
            )
        )
        .where(
            or_(
                database_models.ChildDistanceData.child_id_1 == child_id,
                database_models.ChildDistanceData.child_id_2 == child_id
            ),
            database_models.ChildDistanceData.date >= start_date,
            database_models.ChildDistanceData.date <= end_date
        )
        .order_by(database_models.ChildDistanceData.date)
    )).all()

    distances = []
    for record, other_name in distance_records:
        # 相手IDを取得
        other_id = (
            record.child_id_2
            if record.child_id_1 == child_id
            else record.child_id_1
        )
        distances.append(http_models.ChildDistance(
            with_child=other_id,
            other_name=other_name,
            distance=record.distance,
            date=record.date
        ))

    # 統計情報
    total_distance = sum(d.distance for d in distances)
    avg_distance = total_distance / len(distances) if distances else 0
    max_distance_record = (
        max(distances, key=lambda d: d.distance)
        if distances
        else None
    )
    min_distance_record = (
        min(distances, key=lambda d: d.distance)
        if distances
        else None
    )

    return http_models.ChildDistancesResponse(
        status="ok",
        child_id=child_id,
        name=child.name,
        device_id=child.device_id,
        date=start_date,
        distances=distances,
        total_distance=total_distance,
        avg_distance=avg_distance,
        max_distance=http_models.DistanceStat(
            with_child=max_distance_record.with_child if max_distance_record else 0,
            distance=max_distance_record.distance if max_distance_record else 0
        ),
        min_distance=http_models.DistanceStat(
            with_child=min_distance_record.with_child if min_distance_record else 0,
            distance=min_distance_record.distance if min_distance_record else 0
        ),
        meeting_count=len(distances)
    )


@app.get("/api/stats/distance-today", tags=["API"])
async def get_distance_today_stats(
    dbsession: database_models.SessionDep,
    year: int = datetime.datetime.now().year,
    month: int = datetime.datetime.now().month,
    day: int = datetime.datetime.now().day,
) -> http_models.DistanceStatsResponse:
    """指定日の距離合計、児童別統計、上位ペアを返す。"""
    start_date = datetime.datetime(year, month, day, 0, 0, 0)
    end_date = datetime.datetime(year, month, day, 23, 59, 59)

    # 全距離データを取得 - テーブルにエイリアスを使用
    Child2 = sqlalchemy.orm.aliased(database_models.Child)
    distance_records = (await dbsession.execute(
        sqlalchemy.select(
            database_models.ChildDistanceData,
            database_models.Child.name.label('child1_name'),
            Child2.name.label('child2_name')
        )
        .outerjoin(
            database_models.Child,
            database_models.ChildDistanceData.child_id_1 == database_models.Child.child_id
        )
        .outerjoin(
            Child2,
            database_models.ChildDistanceData.child_id_2 == Child2.child_id
        )
        .where(
            database_models.ChildDistanceData.date >= start_date,
            database_models.ChildDistanceData.date <= end_date
        )
    )).all()

    # 距離データを集計
    total_distance = 0
    meeting_count = 0
    distance_by_pair = {}
    child_distances = {}

    for record, name1, name2 in distance_records:
        total_distance += record.distance
        meeting_count += 1

        pair_key = (record.child_id_1, record.child_id_2)
        pair_names = (
            name1 or f"Child{record.child_id_1}",
            name2 or f"Child{record.child_id_2}"
        )
        distance_by_pair[pair_key] = {
            "child_id_1": record.child_id_1,
            "child_id_2": record.child_id_2,
            "name1": pair_names[0],
            "name2": pair_names[1],
            "distance": record.distance
        }

        # 各児童の距離
        if record.child_id_1 not in child_distances:
            child_distances[record.child_id_1] = {
                "total": 0,
                "count": 0,
                "name": name1 or f"Child{record.child_id_1}"
            }
        child_distances[record.child_id_1]["total"] += record.distance
        child_distances[record.child_id_1]["count"] += 1

        if record.child_id_2 not in child_distances:
            child_distances[record.child_id_2] = {
                "total": 0,
                "count": 0,
                "name": name2 or f"Child{record.child_id_2}"
            }
        child_distances[record.child_id_2]["total"] += record.distance
        child_distances[record.child_id_2]["count"] += 1

    # 児童別統計
    student_stats = []
    for cid, data in child_distances.items():
        child = await dbsession.get(database_models.Child, cid)
        student_stats.append(http_models.StudentDistanceStat(
            child_id=cid,
            name=data["name"],
            total_distance=data["total"],
            avg_distance=(
                data["total"] / data["count"]
                if data["count"] > 0
                else 0
            ),
            meeting_count=data["count"]
        ))

    student_stats.sort(key=lambda x: x.total_distance, reverse=True)

    return http_models.DistanceStatsResponse(
        status="ok",
        date=start_date,
        total_distance=total_distance,
        meeting_count=meeting_count,
        avg_distance=(
            total_distance / meeting_count
            if meeting_count > 0
            else 0
        ),
        student_stats=student_stats,
        top_pairs=sorted(
            distance_by_pair.values(),
            key=lambda x: x["distance"],
            reverse=True
        )[:5]
    )


@app.get("/api/stats/monthly", tags=["API"])
async def get_monthly_stats(
    dbsession: database_models.SessionDep,
    year: int = datetime.datetime.now().year,
    month: int = datetime.datetime.now().month,
) -> http_models.MonthlyStatsResponse:
    """指定月の歩数合計、距離合計、月末日、残日数を返す。"""
    import calendar

    # 月の最終日
    last_day = calendar.monthrange(year, month)[1]

    month_start = datetime.datetime(year, month, 1, 0, 0, 0)
    month_end = datetime.datetime(year, month, last_day, 23, 59, 59)

    # 月間の全歩数データ
    all_step_data = (await dbsession.execute(
        sqlalchemy.select(database_models.SingleChildData)
        .where(
            database_models.SingleChildData.date >= month_start,
            database_models.SingleChildData.date <= month_end
        )
    )).scalars().all()

    month_total_steps = sum(d.steps for d in all_step_data)

    # 月間の全距離データ
    all_distance_data = (await dbsession.execute(
        sqlalchemy.select(database_models.ChildDistanceData)
        .where(
            database_models.ChildDistanceData.date >= month_start,
            database_models.ChildDistanceData.date <= month_end
        )
    )).scalars().all()

    month_total_distance = sum(d.distance for d in all_distance_data)

    # 残日数
    today = datetime.datetime.now()
    if today.year == year and today.month == month:
        remaining_days = last_day - today.day
    else:
        remaining_days = 0

    return http_models.MonthlyStatsResponse(
        status="ok",
        year=year,
        month=month,
        total_steps=month_total_steps,
        total_distance=month_total_distance,
        remaining_days=remaining_days,
        last_day=last_day
    )


# APIルートを先に登録した後でフロントエンドを配信する。
app.mount(
    "/",
    StaticFiles(directory=(pathlib.Path(__file__).parent.parent / "frontend").resolve(), html=True),
    name="frontend",
)
