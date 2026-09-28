import datetime
import numpy as np
from sqlalchemy import and_, or_, select, func

# uv側がPythonパッケージとして別のGitHubリポジトリからモジュールをインストール
import sukusute_machine_learning.inference.predict_behavior
import sukusute_machine_learning.inference.predict_distance
import sukusute_machine_learning.utils.baseline
import sukusute_machine_learning.utils.relatedness

import sukusute_server.database_models

async def evaluate_data(dbsession: sukusute_server.database_models.SessionDep,
                        child_id: int,
                        distance_child_ids: list[int]) -> None:
    # ある1人の児童の計測データ（歩数・加速度）を取得
    if await dbsession.scalar(select(func.count()) \
            .select_from(sukusute_server.database_models.ChildBehaviorDataEvaluationHistory)
            .where(sukusute_server.database_models.ChildBehaviorDataEvaluationHistory.date >= datetime.datetime.now() - datetime.timedelta(minutes=10))):
        return

    single_stmt = select(sukusute_server.database_models.SingleChildData) \
                    .where(
                        sukusute_server.database_models.SingleChildData.child_id == child_id,
                    ) \
                    .order_by(sukusute_server.database_models.SingleChildData.date.asc())
    single_records = (await dbsession.execute(single_stmt)).scalars().all()

    # 直近10分間の計測データとして取得
    single_records_10min = [record for record in single_records if record.date > datetime.datetime.now()-datetime.timedelta(minutes=11)][:6000]
    if len(single_records_10min) < 6000:
        return

    # behavior_inferへの入力形式を作成
    behavior_input = np.fromiter(((
        record.steps,
        record.ax, record.ay, record.az,
        record.gx, record.gy, record.gz,
        record.mx, record.my, record.mz
    ) for record in single_records_10min), dtype=(np.float32, 10))

    # 直近10分間の歩数・加速度の計測データから分類ラベルを推定
    behavior_result = sukusute_machine_learning.inference.predict_behavior.behavior_infer(behavior_input)
    del behavior_input, single_records_10min

    # activity_inferへの入力形式を作成
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

    # build_baselineへの入力形式を作成
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

    # ある1人の児童と相手デバイスとの相対距離の計測データを取得
    distance_stmt = select(sukusute_server.database_models.ChildDistanceData) \
        .where(or_(
            sukusute_server.database_models.ChildDistanceData.child_id_1 == child_id,
            sukusute_server.database_models.ChildDistanceData.child_id_2 == child_id,
        )) \
        .order_by(sukusute_server.database_models.ChildDistanceData.date.asc())
    distance_records = (await dbsession.execute(distance_stmt)).scalars().all()

    # 直近10分間の計測データとして取得
    # それぞれの相手デバイスに対してdistance_inferへの入力形式を作成
    distance_records_10min = [record for record in distance_records if record.date > datetime.datetime.now()-datetime.timedelta(minutes=11)]
    for other_child_id in distance_child_ids:
        if child_id > other_child_id:
            child_distance_records_10min = [record for record in distance_records_10min if record.child_id_1 == other_child_id][:6000]
        else:
            child_distance_records_10min = [record for record in distance_records_10min if record.child_id_2 == other_child_id][:6000]
        if len(child_distance_records_10min) < 6000:
            return
        distance_input = np.fromiter((record.distance for record in child_distance_records_10min), dtype=np.float32)

        # それぞれの相手デバイスに対して直近10分間の相対距離の計測データから分類ラベルを推定
        distance_result = sukusute_machine_learning.inference.predict_distance.distance_infer(distance_input)

        # 過去の相対距離の分類ラベルの推論結果を取得
        distance_evalhist_stmt = select(sukusute_server.database_models.ChildDistanceEvaluationHistory.evaluated) \
            .where(and_(
                sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1 == min((child_id, other_child_id)),
                sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2 == max((child_id, other_child_id)),
            )) \
            .order_by(sukusute_server.database_models.ChildDistanceEvaluationHistory.date.asc())
        distance_evalhist_records = (await dbsession.execute(distance_evalhist_stmt)).scalars().all()

        # 過去の相対距離の分類ラベルの推論結果から関連度スコアを算出
        relatedness_result = sukusute_machine_learning.utils.relatedness.calc_relatedness(distance_evalhist_records)

        # 距離・関係度スコアの評価結果をDBに保存
        dbsession.add(sukusute_server.database_models.ChildDistanceEvaluationHistory(
            child_id_1=min((child_id, other_child_id)),
            child_id_2=max((child_id, other_child_id)),
            date=datetime.datetime.now(),
            evaluated=sukusute_server.database_models.ChildDistanceEvaluationEnum(distance_result["label"]),
            confidence=distance_result["confidence"],
            score=relatedness_result
        ))

    await dbsession.commit()
