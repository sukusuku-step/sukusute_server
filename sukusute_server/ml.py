import datetime
import numpy as np
from sqlalchemy import and_, or_, select, func

# uv側がPythonパッケージとして別のGitHubリポジトリからモジュールをインストール
import sukusute_machine_learning.inference.predict_behavior
import sukusute_machine_learning.inference.predict_distance
import sukusute_machine_learning.utils.baseline
import sukusute_machine_learning.utils.relatedness

import sukusute_server.database_models

ANOMALY_THRESHOLD_RATIO = 0.050 # 異常検知のしきい値（何%内まで正常とみなすか）
ANOMALY_EPS = 1e-6

latest_anomaly_results: dict[int, dict] = {}

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
def compare_current_with_baseline(current_features: dict[str, float], baseline_result: dict | None, threshold_ratio: float = ANOMALY_THRESHOLD_RATIO) -> dict | None:
    if not baseline_result:
        return None

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

async def evaluate_data(dbsession: sukusute_server.database_models.SessionDep,
                        child_id: int,
                        distance_child_ids: list[int]) -> None:
    # 10秒毎でこのml.pyのバッググランドタスクは呼ばれる
    # 10分単位のデータに対する実行のための（児童ごとに見て）10分以下のスパンでの再実行は早期returnする
    if await dbsession.scalar(
        select(func.count())
        .select_from(
            sukusute_server.database_models.ChildBehaviorDataEvaluationHistory
        )
        .where(
            sukusute_server.database_models.ChildBehaviorDataEvaluationHistory.child_id == child_id,
            sukusute_server.database_models.ChildBehaviorDataEvaluationHistory.date >= datetime.datetime.now() - datetime.timedelta(minutes=10)
        )
    ):
        await evaluate_distance_data(dbsession, child_id, distance_child_ids)
        await dbsession.commit()
        return

    # ある1人の児童の計測データ（歩数・加速度）を取得
    single_stmt = select(sukusute_server.database_models.SingleChildData) \
                    .where(
                        sukusute_server.database_models.SingleChildData.child_id == child_id,
                    ) \
                    .order_by(sukusute_server.database_models.SingleChildData.date.asc())
    single_records = (await dbsession.execute(single_stmt)).scalars().all()

    # 直近10分間の計測データとして取得
    single_records_10min = [record for record in single_records if record.date > datetime.datetime.now()-datetime.timedelta(minutes=11)][-6000:]
    if len(single_records_10min) < 6000:
        await evaluate_distance_data(dbsession, child_id, distance_child_ids)
        await dbsession.commit()
        return

    current_10min_features = calculate_current_10min_features(single_records_10min)

    # behavior_inferへの入力形式を作成（過去10分単位）
    behavior_input = np.fromiter(((
        record.steps,
        record.ax, record.ay, record.az,
        record.gx, record.gy, record.gz,
        record.mx, record.my, record.mz
    ) for record in single_records_10min), dtype=(np.float32, 10))

    # 直近10分間の歩数・加速度の計測データから分類ラベルを推定
    behavior_result = sukusute_machine_learning.inference.predict_behavior.behavior_infer(behavior_input)
    del behavior_input, single_records_10min

    # activity_inferへの入力形式を作成（1時間までの取れる分の過去データ）
    single_records_1h = [record for record in single_records if record.date > datetime.datetime.now() - datetime.timedelta(hours=1)]
    activity_input = np.fromiter(((
        record.steps,
        record.ax, record.ay, record.az,
        record.gx, record.gy, record.gz,
        record.mx, record.my, record.mz
    ) for record in single_records_1h), dtype=(np.float32, 10))

    # 直近1時間の歩数・加速度の計測データから活動量の値を推定
    activity_result = sukusute_machine_learning.inference.predict_behavior.activity_infer(activity_input)
    del activity_input, single_records_1h

    # build_baselineへの入力形式を作成（取れる分の全ての過去データ）
    baseline_input = np.fromiter(((
        record.steps,
        record.ax, record.ay, record.az,
        record.gx, record.gy, record.gz,
        record.mx, record.my, record.mz
    ) for record in single_records), dtype=(np.float32, 10))

    # 算出したベースライン（medianとmad_scale）を取得
    try:
        baseline_result = sukusute_machine_learning.utils.baseline.build_baseline(baseline_input)["features"]
    except (ValueError, TypeError):
        baseline_result = None

    anomaly_result = compare_current_with_baseline(current_10min_features, baseline_result)
    if anomaly_result:
        latest_anomaly_results[child_id] = {
            "date": datetime.datetime.now().isoformat(),
            **anomaly_result
        }
    else:
        latest_anomaly_results.pop(child_id, None)

    del baseline_input, single_records

    # 歩数・加速度・活動量・ベースラインの評価結果をDBに保存
    dbsession.add(sukusute_server.database_models.ChildBehaviorDataEvaluationHistory(
        child_id=child_id,
        date=datetime.datetime.now(),
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
    ))

    await evaluate_distance_data(dbsession, child_id, distance_child_ids)
    await dbsession.commit()


async def evaluate_distance_data(
    dbsession: sukusute_server.database_models.SessionDep,
    child_id: int,
    distance_child_ids: list[int],
) -> None:
    if not distance_child_ids:
        return

    distance_stmt = select(sukusute_server.database_models.ChildDistanceData) \
        .where(or_(
            sukusute_server.database_models.ChildDistanceData.child_id_1 == child_id,
            sukusute_server.database_models.ChildDistanceData.child_id_2 == child_id,
        )) \
        .order_by(sukusute_server.database_models.ChildDistanceData.date.asc())
    distance_records = (await dbsession.execute(distance_stmt)).scalars().all()
    cutoff = datetime.datetime.now() - datetime.timedelta(minutes=11)
    distance_records_10min = [record for record in distance_records if record.date > cutoff]

    recent_evaluations = (await dbsession.execute(
        select(
            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1,
            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2,
        ).where(
            sukusute_server.database_models.ChildDistanceEvaluationHistory.date >= datetime.datetime.now() - datetime.timedelta(minutes=10),
            or_(
                sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1 == child_id,
                sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2 == child_id,
            ),
        )
    )).all()
    recent_pairs = {(row[0], row[1]) for row in recent_evaluations}

    for other_child_id in set(distance_child_ids):
        pair = (min(child_id, other_child_id), max(child_id, other_child_id))
        if pair in recent_pairs:
            continue

        if child_id > other_child_id:
            pair_records = [record for record in distance_records_10min if record.child_id_1 == other_child_id][:6000]
        else:
            pair_records = [record for record in distance_records_10min if record.child_id_2 == other_child_id][:6000]
        if len(pair_records) < 6000:
            continue

        distance_input = np.fromiter((record.distance for record in pair_records), dtype=np.float32)
        distance_result = sukusute_machine_learning.inference.predict_distance.distance_infer(distance_input)
        history_stmt = select(sukusute_server.database_models.ChildDistanceEvaluationHistory.evaluated) \
            .where(and_(
                sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1 == pair[0],
                sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2 == pair[1],
            )) \
            .order_by(sukusute_server.database_models.ChildDistanceEvaluationHistory.date.asc())
        history = (await dbsession.execute(history_stmt)).scalars().all()
        relatedness_result = sukusute_machine_learning.utils.relatedness.calc_relatedness(history)
        dbsession.add(sukusute_server.database_models.ChildDistanceEvaluationHistory(
            child_id_1=pair[0],
            child_id_2=pair[1],
            date=datetime.datetime.now(),
            evaluated=sukusute_server.database_models.ChildDistanceEvaluationEnum(distance_result["label"]),
            confidence=distance_result["confidence"],
            score=relatedness_result,
        ))