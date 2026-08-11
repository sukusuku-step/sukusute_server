""" すくすくステップ HTTPサーバ """

import logging
import uuid
import datetime
import math
import pathlib

import fastapi
from fastapi.middleware.cors import CORSMiddleware
import sqlalchemy
import sqlalchemy.orm
from sqlalchemy import or_

from sukusute_server import http_models, database_models

logger = logging.getLogger(__name__)

app = fastapi.FastAPI()

# CORSミドルウェア追加 - フロントエンドからのリクエストを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発中は全てを許可（本番では制限すべき）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.frontend("/", directory=(pathlib.Path(__file__).parent.parent / "frontend").resolve())

# ===== ヘルスチェック =====

@app.get("/api/health", tags=["API"])
def health() -> http_models.Result:
    """ サーバが生きていればokを返す """
    return http_models.Result(status="ok")


# ===== データ受信 =====

@app.post("/api/push_data", tags=["API"])
async def push_data(
    data: http_models.ChildDataRecord,
    dbsession: database_models.SessionDep
) -> http_models.Result:
    """ データを受け取る（歩数・距離データ） """
    logger.info(
        f"Received data: child_id={data.child_id}, "
        f"singledata={data.singledata}, distances={data.distances}"
    )

    # 対象児童を取得
    target_child = await dbsession.get(database_models.Child, data.child_id)
    if not target_child:
        raise fastapi.HTTPException(404, f"Child {data.child_id} not found")

    # 距離データを処理
    if data.distances:
        for distance in data.distances:
            # 相手児童を取得
            other_child = await dbsession.get(database_models.Child, distance.with_child)
            if not other_child:
                logger.warning(f"Child {distance.with_child} not found for distance data")
                continue

            # ChildDistanceDataを作成（children setterを使用）
            cdd = database_models.ChildDistanceData(
                distance=distance.distance,
                date=distance.date
            )
            # children setterを呼び出してchild_1, child_2を自動設定
            cdd.children = (target_child, other_child)
            dbsession.add(cdd)
            logger.info(
                f"Added distance: {target_child.name} -> "
                f"{other_child.name} = {distance.distance} km"
            )

    # 単独データを処理
    if data.singledata:
        dbsession.add(database_models.SingleChildData(
            child_id=data.child_id,
            date=data.singledata.date,
            steps=data.singledata.steps
        ))
        logger.info(f"Added steps: {data.child_id} = {data.singledata.steps}")

    await dbsession.commit()
    return http_models.Result(status="ok")


# ===== 児童情報取得 =====

@app.get("/api/children/{child_id:int}", tags=["API"])
async def child_info(
    child_id: int,
    dbsession: database_models.SessionDep
) -> http_models.ChildDataResponse:
    """ 児童のすべての情報（歩数・距離データを含む）を取得 """
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
    """ デバッグ用：児童を作成 """
    child = database_models.Child(
        name="Test Child",
        device_id=uuid.uuid4()
    )
    dbsession.add(child)
    await dbsession.commit()
    return http_models.Result(status="ok")


@app.get("/api/children", tags=["API"])
async def list_children(
    dbsession: database_models.SessionDep
) -> http_models.ChildrenListResponse:
    """ 児童一覧を取得 """
    children = (await dbsession.execute(
        sqlalchemy.select(database_models.Child)
        .order_by(database_models.Child.child_id)
    )).scalars().all()

    return http_models.ChildrenListResponse(
        status="ok",
        children=[
            http_models.ChildListItem(
                child_id=child.child_id,
                name=child.name,
                device_id=child.device_id
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
    """ 特定児童の歩数データを取得 """
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
    walk_time = math.floor(today_steps / 150)
    # カロリ（歩数*0.008）
    calories = math.floor(today_steps * 0.008)

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
        goal_met=today_steps >= 10000
    )


@app.get("/api/children/{child_id:int}/steps/history", tags=["API"])
async def get_child_steps_history(
    child_id: int,
    dbsession: database_models.SessionDep,
    days: int = 7,
) -> http_models.ChildStepsHistoryResponse:
    """ 特定児童の歩数履歴を取得 """
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
    """ 今日の集計情報を取得 """
    start_date = datetime.datetime(year, month, day, 0, 0, 0)
    end_date = datetime.datetime(year, month, day, 23, 59, 59)

    logger.info(
        f"get_today_stats: year={year}, month={month}, day={day}"
    )

    # 全児童のその日の最新の歩数データ
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
    for child_id, name, steps_val, date_val in all_step_data:
        if child_id not in student_steps:
            student_steps[child_id] = steps_val
            student_child_ids[name] = child_id

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
    walk_time = math.floor(total_steps / 150)
    calories = math.floor(total_steps * 0.008)
    goal_met_count = sum(1 for s in student_steps.values() if s >= 10000)

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
    for child_id_val, name, steps_val, date_val in list(all_step_data):
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
            if avg_weekly > 0 and steps_val < avg_weekly * 0.5:
                warnings.append(http_models.StepWarning(
                    child_id=child_id_val,
                    name=name,
                    current_steps=steps_val,
                    average_steps=math.floor(avg_weekly),
                    percent=math.floor(steps_val / avg_weekly * 100)
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
    for child in all_children:
        steps = student_steps.get(child.child_id, 0)
        student_ranking.append(http_models.StudentRankingItem(
            child_id=child.child_id,
            name=child.name,
            steps=steps
        ))
    student_ranking.sort(key=lambda x: x.steps, reverse=True)

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
    """ 特定児童の距離データを取得 """
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
    """ 今日の距離データの集計情報を取得 """
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
    """ 月間集計情報を取得 """
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
