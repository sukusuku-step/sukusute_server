import datetime
import asyncio
import logging
import numpy as np
from sqlalchemy import and_, select, func

# uv側がPythonパッケージとして別のGitHubリポジトリからモジュールをインストール
import sukusute_machine_learning.inference.predict_behavior
import sukusute_machine_learning.inference.predict_distance
import sukusute_machine_learning.utils.baseline
import sukusute_machine_learning.utils.relatedness

import sukusute_server.database_models

logger = logging.getLogger(__name__)

# ===== フロントエンドのコンフィグから変更可能なML設定 =====

# サーバを再起動すると以下のデフォルト値に戻る

# activity_inferへ渡す過去データ量の上限（単位: 分）
ACTIVITY_MAX_DATA_MINUTES = 60

# 何%ベースラインから外れたら異常値とみなすか（例: 0.50 = 50%）
ANOMALY_THRESHOLD_RATIO = 0.10

# build_baselineを実行するために最低限必要な過去データ量（単位: 分）
BASELINE_MIN_DATA_MINUTES = 5

# build_baselineへ渡すデータは最大で過去何日分までか
BASELINE_MAX_DAYS = 14

# calc_relatednessへ渡す過去の相対距離の推論結果の最大件数
RELATEDNESS_MAX_HISTORY = 100

# calc_relatednessへ渡すデータは最大で過去何日分までか
RELATEDNESS_MAX_STEPS_MINUTES = 14

ANOMALY_EPS = 1e-6

latest_anomaly_results: dict[int, dict] = {}

# 実際に推論を実行した時刻はサーバのメモリ上で別管理する（DBのdateは推論・progress用の境界として使用）
# Freshnessはサーバの再起動時には一度全て色を薄くする仕様なのでこれで良い
latest_behavior_evaluated_at: dict[int, datetime.datetime] = {}
latest_distance_evaluated_at: dict[tuple[int, int], datetime.datetime] = {}

ml_inference_semaphore = asyncio.Semaphore(1)
behavior_evaluation_locks: dict[int, asyncio.Lock] = {}
distance_evaluation_locks: dict[tuple[int, int], asyncio.Lock] = {}

async def run_ml_inference(function, *args):
    async with ml_inference_semaphore:
        return await asyncio.to_thread(function, *args)

def get_ml_config() -> dict:
    return {
        "activity_max_data_minutes": ACTIVITY_MAX_DATA_MINUTES,
        "anomaly_threshold_ratio": ANOMALY_THRESHOLD_RATIO,
        "baseline_min_data_minutes": BASELINE_MIN_DATA_MINUTES,
        "baseline_max_days": BASELINE_MAX_DAYS,
        "relatedness_max_history": RELATEDNESS_MAX_HISTORY
    }

def update_ml_config(
    activity_max_data_minutes: int,
    anomaly_threshold_ratio: float,
    baseline_min_data_minutes: int,
    baseline_max_days: int,
    relatedness_max_history: int
) -> dict:
    global ACTIVITY_MAX_DATA_MINUTES
    global ANOMALY_THRESHOLD_RATIO
    global BASELINE_MIN_DATA_MINUTES
    global BASELINE_MAX_DAYS
    global RELATEDNESS_MAX_HISTORY

    ACTIVITY_MAX_DATA_MINUTES = activity_max_data_minutes
    ANOMALY_THRESHOLD_RATIO = anomaly_threshold_ratio
    BASELINE_MIN_DATA_MINUTES = baseline_min_data_minutes
    BASELINE_MAX_DAYS = baseline_max_days
    RELATEDNESS_MAX_HISTORY = relatedness_max_history

    return get_ml_config()

def calculate_current_10min_features(records) -> dict[str, float]:
    steps = np.asarray([record.steps for record in records], dtype=np.float32)
    step_diff = np.diff(steps, prepend=steps[0])
    step_diff = np.clip(step_diff, 0, None)

    ax = np.asarray([record.ax for record in records], dtype=np.float32)
    ay = np.asarray([record.ay for record in records], dtype=np.float32)
    az = np.asarray([record.az for record in records], dtype=np.float32)
    gx = np.asarray([record.gx for record in records], dtype=np.float32)
    gy = np.asarray([record.gy for record in records], dtype=np.float32)
    gz = np.asarray([record.gz for record in records], dtype=np.float32)
    mx = np.asarray([record.mx for record in records], dtype=np.float32)
    my = np.asarray([record.my for record in records], dtype=np.float32)
    mz = np.asarray([record.mz for record in records], dtype=np.float32)

    acc_mag = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
    gyro_mag = np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
    mag_mag = np.sqrt(mx ** 2 + my ** 2 + mz ** 2)

    return {
        "steps_10min": float(np.nansum(step_diff)),
        "activity_mean_proxy": float(np.nanmean(acc_mag)),
        "acc_std": float(np.nanstd(acc_mag, ddof=1)),
        "gyro_mean": float(np.nanmean(gyro_mag)),
        "mag_mean": float(np.nanmean(mag_mag))
    }

# 異常検知システムのために、10分間での計測データがベースラインとどれだけ外れているのかを計算する
def compare_current_with_baseline(
    current_features: dict[str, float],
    baseline_result: dict | None,
    threshold_ratio: float | None = None,
) -> dict | None:
    if not baseline_result:
        return None

    # 何%ベースラインから外れたら異常値とみなすかのしきい値を設定
    if threshold_ratio is None:
        threshold_ratio = ANOMALY_THRESHOLD_RATIO

    comparisons = {}
    warning = False

    for feature, current_value in current_features.items():
        baseline_feature = baseline_result.get(feature)
        if not baseline_feature:
            continue

        baseline_median = float(baseline_feature["median"])
        baseline_mad_scale = float(baseline_feature["mad_scale"])

        if not np.isfinite(current_value) or not np.isfinite(baseline_median):
            continue

        reference_value = abs(baseline_median)
        if reference_value < ANOMALY_EPS:
            reference_value = max(abs(baseline_mad_scale), ANOMALY_EPS)

        relative_diff = abs(current_value - baseline_median) / reference_value
        feature_warning = relative_diff >= threshold_ratio
        warning = warning or feature_warning # しきい値のパーセントよりも乖離していたらwarningをtrueにする

        comparisons[feature] = {
            "current": float(current_value),
            "baseline_median": baseline_median,
            "baseline_mad_scale": baseline_mad_scale,
            "relative_diff": float(relative_diff),
            "relative_diff_percent": float(relative_diff * 100.0),
            "warning": bool(feature_warning)
        }

    return {
        "warning": bool(warning),
        "threshold_ratio": float(threshold_ratio),
        "threshold_percent": float(threshold_ratio * 100.0),
        "comparisons": comparisons
    }

async def _latest_behavior_processed_boundary(dbsession, child_id: int):
    """旧/新どちらの履歴dateでも、実データ上の処理済み境界へ正規化する。"""
    latest_evaluation_date = await dbsession.scalar(
        select(func.max(
            sukusute_server.database_models.ChildBehaviorDataEvaluationHistory.date
        )).where(
            sukusute_server.database_models.ChildBehaviorDataEvaluationHistory.child_id == child_id
        )
    )
    if latest_evaluation_date is None:
        return None
    return await dbsession.scalar(
        select(func.max(sukusute_server.database_models.SingleChildData.date)).where(
            sukusute_server.database_models.SingleChildData.child_id == child_id,
            sukusute_server.database_models.SingleChildData.date <= latest_evaluation_date,
        )
    )


async def get_behavior_progress(dbsession, child_id: int) -> tuple[datetime.datetime | None, int]:
    """behavior推論とprogress表示で共通利用する未処理行数をDBから算出する。"""
    processed_boundary = await _latest_behavior_processed_boundary(dbsession, child_id)
    count_stmt = select(func.count()).select_from(
        sukusute_server.database_models.SingleChildData
    ).where(
        sukusute_server.database_models.SingleChildData.child_id == child_id
    )
    if processed_boundary is not None:
        count_stmt = count_stmt.where(
            sukusute_server.database_models.SingleChildData.date > processed_boundary
        )
    pending_rows = int(await dbsession.scalar(count_stmt) or 0)
    return processed_boundary, pending_rows


async def evaluate_data(dbsession: sukusute_server.database_models.SessionDep,
                        child_id: int,
                        distance_child_ids: list[int]) -> None:
    lock = behavior_evaluation_locks.setdefault(child_id, asyncio.Lock())
    async with lock:
        while True:
            processed_boundary = await _latest_behavior_processed_boundary(
                dbsession, child_id
            )

            pending_stmt = select(
                sukusute_server.database_models.SingleChildData
            ).where(
                sukusute_server.database_models.SingleChildData.child_id == child_id
            )

            if processed_boundary is not None:
                # 2回目以降: 前回処理済み境界より後の最古6000行を順番に消化する。
                pending_stmt = pending_stmt.where(
                    sukusute_server.database_models.SingleChildData.date > processed_boundary
                ).order_by(
                    sukusute_server.database_models.SingleChildData.date.asc()
                ).limit(6000)
                single_records_10min = (
                    await dbsession.execute(pending_stmt)
                ).scalars().all()
            else:
                # 初回: DBに過去データが大量にあっても最新6000行を使う。
                pending_stmt = pending_stmt.order_by(
                    sukusute_server.database_models.SingleChildData.date.desc()
                ).limit(6000)
                single_records_10min = list(reversed(
                    (await dbsession.execute(pending_stmt)).scalars().all()
                ))

            if len(single_records_10min) < 6000:
                break

            evaluation_data_end = single_records_10min[-1].date
            current_10min_features = calculate_current_10min_features(
                single_records_10min
            )

            behavior_input = np.fromiter(((
                record.steps,
                record.ax, record.ay, record.az,
                record.gx, record.gy, record.gz,
                record.mx, record.my, record.mz
            ) for record in single_records_10min), dtype=(np.float32, 10))
            behavior_result = await run_ml_inference(
                sukusute_machine_learning.inference.predict_behavior.behavior_infer,
                behavior_input
            )
            del behavior_input

            history_cutoff = min(
                evaluation_data_end - datetime.timedelta(minutes=ACTIVITY_MAX_DATA_MINUTES),
                evaluation_data_end - datetime.timedelta(days=BASELINE_MAX_DAYS),
            )
            single_records = (
                await dbsession.execute(
                    select(sukusute_server.database_models.SingleChildData)
                    .where(
                        sukusute_server.database_models.SingleChildData.child_id == child_id,
                        sukusute_server.database_models.SingleChildData.date >= history_cutoff,
                        sukusute_server.database_models.SingleChildData.date <= evaluation_data_end,
                    )
                    .order_by(sukusute_server.database_models.SingleChildData.date.asc())
                )
            ).scalars().all()

            activity_cutoff = evaluation_data_end - datetime.timedelta(
                minutes=ACTIVITY_MAX_DATA_MINUTES
            )
            activity_records = [
                record for record in single_records
                if record.date >= activity_cutoff
            ]

            # activity_infer は最低6000サンプルを要求する。
            # 時刻ベースの履歴窓が疎で6000件未満になった場合でも、
            # 今回behavior推論に使用した6000件を下限として利用する。
            if len(activity_records) < 6000:
                activity_records = list(single_records_10min)

            activity_input = np.fromiter(((
                record.steps,
                record.ax, record.ay, record.az,
                record.gx, record.gy, record.gz,
                record.mx, record.my, record.mz
            ) for record in activity_records), dtype=(np.float32, 10))
            activity_result = await run_ml_inference(
                sukusute_machine_learning.inference.predict_behavior.activity_infer,
                activity_input
            )
            del activity_input, activity_records

            baseline_records = list(single_records)
            baseline_result = None
            baseline_input = None
            has_enough_baseline_history = (
                len(baseline_records) >= 2
                and baseline_records[-1].date - baseline_records[0].date
                >= datetime.timedelta(minutes=BASELINE_MIN_DATA_MINUTES)
            )

            if has_enough_baseline_history:
                baseline_input = np.fromiter(((
                    record.steps,
                    record.ax, record.ay, record.az,
                    record.gx, record.gy, record.gz,
                    record.mx, record.my, record.mz
                ) for record in baseline_records), dtype=(np.float32, 10))
                try:
                    baseline_result = (await run_ml_inference(
                        sukusute_machine_learning.utils.baseline.build_baseline,
                        baseline_input
                    ))["features"]
                except (ValueError, TypeError, KeyError) as error:
                    logger.warning(
                        "baseline calculation failed for child_id=%s: %s",
                        child_id,
                        error,
                    )
            else:
                logger.info(
                    "baseline skipped for child_id=%s: history span is shorter than %s minutes",
                    child_id,
                    BASELINE_MIN_DATA_MINUTES,
                )

            anomaly_result = compare_current_with_baseline(
                current_10min_features, baseline_result
            )
            if anomaly_result:
                latest_anomaly_results[child_id] = {
                    "date": datetime.datetime.now().isoformat(),
                    **anomaly_result
                }
            else:
                latest_anomaly_results.pop(child_id, None)

            del baseline_input, baseline_records, single_records

            # dateを「今回処理した6000行目の計測時刻」として保存する（境界として使う）
            # progressも同じ境界を使うため、6000行ちょうどならcommit後に0%へ戻る
            dbsession.add(
                sukusute_server.database_models.ChildBehaviorDataEvaluationHistory(
                    child_id=child_id,
                    date=evaluation_data_end,
                    behavior_acce=sukusute_server.database_models.ChildBehaviorAcceEnum(behavior_result["acce_label"]),
                    behavior_acce_confidence=behavior_result["acce_confidence"],
                    behavior_pedo=sukusute_server.database_models.ChildBehaviorPedoEnum(behavior_result["pedo_label"]),
                    behavior_pedo_confidence=behavior_result["pedo_confidence"],
                    activity=activity_result["activity_level"],
                    activity_confidence=activity_result["activity_confidence"],
                    baseline_steps_10min_median=baseline_result["steps_10min"]["median"] if baseline_result else None,
                    baseline_steps_10min_mad_scale=baseline_result["steps_10min"]["mad_scale"] if baseline_result else None,
                    baseline_activity_mean_proxy_median=baseline_result["activity_mean_proxy"]["median"] if baseline_result else None,
                    baseline_activity_mean_proxy_mad_scale=baseline_result["activity_mean_proxy"]["mad_scale"] if baseline_result else None,
                    baseline_acc_std_median=baseline_result["acc_std"]["median"] if baseline_result else None,
                    baseline_acc_std_mad_scale=baseline_result["acc_std"]["mad_scale"] if baseline_result else None,
                    baseline_gyro_mean_median=baseline_result["gyro_mean"]["median"] if baseline_result else None,
                    baseline_gyro_mean_mad_scale=baseline_result["gyro_mean"]["mad_scale"] if baseline_result else None,
                    baseline_mag_mean_median=baseline_result["mag_mean"]["median"] if baseline_result else None,
                    baseline_mag_mean_mad_scale=baseline_result["mag_mean"]["mad_scale"] if baseline_result else None
                )
            )
            await dbsession.commit()

            # commitが正常終了した時点をFreshness用の推論時刻として記録
            latest_behavior_evaluated_at[child_id] = datetime.datetime.now()

        await evaluate_distance_data(dbsession, child_id, distance_child_ids)
        await dbsession.commit()


async def _latest_distance_processed_boundary(dbsession, pair: tuple[int, int]):
    latest_evaluation_date = await dbsession.scalar(
        select(func.max(
            sukusute_server.database_models.ChildDistanceEvaluationHistory.date
        )).where(and_(
            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1 == pair[0],
            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2 == pair[1],
        ))
    )
    if latest_evaluation_date is None:
        return None
    return await dbsession.scalar(
        select(func.max(sukusute_server.database_models.ChildDistanceData.date)).where(
            sukusute_server.database_models.ChildDistanceData.child_id_1 == pair[0],
            sukusute_server.database_models.ChildDistanceData.child_id_2 == pair[1],
            sukusute_server.database_models.ChildDistanceData.date <= latest_evaluation_date,
        )
    )


async def evaluate_distance_data(
    dbsession: sukusute_server.database_models.SessionDep,
    child_id: int,
    distance_child_ids: list[int]
) -> None:
    if not distance_child_ids:
        return

    for other_child_id in set(distance_child_ids):
        pair = (min(child_id, other_child_id), max(child_id, other_child_id))
        pair_lock = distance_evaluation_locks.setdefault(pair, asyncio.Lock())

        async with pair_lock:
            while True:
                processed_boundary = await _latest_distance_processed_boundary(
                    dbsession, pair
                )
                stmt = select(
                    sukusute_server.database_models.ChildDistanceData
                ).where(
                    sukusute_server.database_models.ChildDistanceData.child_id_1 == pair[0],
                    sukusute_server.database_models.ChildDistanceData.child_id_2 == pair[1],
                )
                if processed_boundary is not None:
                    stmt = stmt.where(
                        sukusute_server.database_models.ChildDistanceData.date > processed_boundary
                    ).order_by(
                        sukusute_server.database_models.ChildDistanceData.date.asc()
                    ).limit(6000)
                    records = (await dbsession.execute(stmt)).scalars().all()
                else:
                    stmt = stmt.order_by(
                        sukusute_server.database_models.ChildDistanceData.date.desc()
                    ).limit(6000)
                    records = list(reversed(
                        (await dbsession.execute(stmt)).scalars().all()
                    ))

                if len(records) < 6000:
                    break

                evaluation_data_end = records[-1].date
                distance_input = np.fromiter(
                    (record.distance for record in records), dtype=np.float32
                )
                distance_result = await run_ml_inference(
                    sukusute_machine_learning.inference.predict_distance.distance_infer,
                    distance_input
                )

                history = (
                    await dbsession.execute(
                        select(
                            sukusute_server.database_models.ChildDistanceEvaluationHistory.evaluated
                        )
                        .where(and_(
                            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1 == pair[0],
                            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2 == pair[1],
                        ))
                        .order_by(
                            sukusute_server.database_models.ChildDistanceEvaluationHistory.date.desc()
                        )
                        .limit(RELATEDNESS_MAX_HISTORY)
                    )
                ).scalars().all()
                relatedness_result = await run_ml_inference(
                    sukusute_machine_learning.utils.relatedness.calc_relatedness,
                    history
                )

                dbsession.add(
                    sukusute_server.database_models.ChildDistanceEvaluationHistory(
                        child_id_1=pair[0],
                        child_id_2=pair[1],
                        date=evaluation_data_end,
                        evaluated=sukusute_server.database_models.ChildDistanceEvaluationEnum(distance_result["label"]),
                        confidence=distance_result["confidence"],
                        score=relatedness_result
                    )
                )
                await dbsession.commit()

                # commitが正常終了した時点をFreshness用の推論時刻として記録
                latest_distance_evaluated_at[pair] = datetime.datetime.now()