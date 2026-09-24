import typing
import datetime
import numpy as np

from sqlalchemy import and_, or_, select
import sukusute_machine_learning.inference.predict_behavior
import sukusute_machine_learning.inference.predict_distance
import sukusute_machine_learning.utils.baseline
import sukusute_machine_learning.utils.relatedness

import sukusute_server.database_models

async def evaluate_data(dbsession: sukusute_server.database_models.SessionDep,
                        child_id: int):
    single_stmt = select(sukusute_server.database_models.SingleChildData) \
                    .where(
                        sukusute_server.database_models.SingleChildData.child_id == child_id,
                    ) \
                    .order_by(sukusute_server.database_models.SingleChildData.date.asc())
    single_records = (await dbsession.execute(single_stmt)).scalars().all()
    single_records_10min = [record for record in single_records if record.date > datetime.datetime.now()-datetime.timedelta(minutes=10)][:6000]
    if len(single_records_10min) < 6000:
        return
    behavior_input = np.fromiter(((
        record.steps,
        record.ax, record.ay, record.az,
        record.gx, record.gy, record.gz,
        record.mx, record.my, record.mz
    ) for record in single_records_10min), dtype=np.float32)
    behavior_result = sukusute_machine_learning.inference.predict_behavior.behavior_infer(behavior_input)
    activity_result = sukusute_machine_learning.inference.predict_behavior.activity_infer(behavior_input)
    
    baseline_input = np.fromiter(((
        record.steps,
        record.ax, record.ay, record.az,
        record.gx, record.gy, record.gz,
        record.mx, record.my, record.mz
    ) for record in single_records), dtype=np.float32)
    baseline_result = sukusute_machine_learning.utils.baseline.build_baseline(baseline_input)["features"]

    dbsession.add(sukusute_server.database_models.ChildBehaviorDataEvaluationHistory(
        date=datetime.datetime.now(),
        behavior_acce=sukusute_server.database_models.ChildBehaviorEvaluationEnum(behavior_result["acce_label"]),
        behavior_acce_confidence=behavior_result["acce_confidence"],
        behavior_pedo=sukusute_server.database_models.ChildBehaviorEvaluationEnum(behavior_result["pedo_label"]),
        behavior_pedo_confidence=behavior_result["pedo_confidence"],
        activity=activity_result["activity_level"],
        activity_confidence=activity_result["activity_confidence"],
        baseline_steps_10min_median=baseline_result["steps_10min"]["median"],
        baseline_steps_10min_mad_scale=baseline_result["steps_10min"]["mad_scale"],
        baseline_activity_mean_proxy_median=baseline_result["activity_mean_proxy"]["median"],
        baseline_activity_mean_proxy_mad_scale=baseline_result["activity_mean_proxy"]["mad_scale"],
        baseline_acc_std_median=baseline_result["acc_std"]["median"],
        baseline_acc_std_mad_scale=baseline_result["acc_std"]["mad_scale"],
        baseline_gyro_mean_median=baseline_result["gyro_mean"]["median"],
        baseline_gyro_mean_mad_scale=baseline_result["gyro_mean"]["mad_scale"],
        baseline_mag_mean_median=baseline_result["mag_mean"]["median"],
        baseline_mag_mean_mad_scale=baseline_result["mag_mean"]["mad_scale"]
    ))

    distance_stmt = select(sukusute_server.database_models.ChildDistanceData) \
        .where(or_(
            sukusute_server.database_models.ChildDistanceData.child_id_1 == child_id,
            sukusute_server.database_models.ChildDistanceData.child_id_2 == child_id,
        )) \
        .order_by(sukusute_server.database_models.ChildDistanceData.date.asc())
    distance_records = (await dbsession.execute(distance_stmt)).scalars().all()
    distance_records_10min = [record for record in distance_records if record.date > datetime.datetime.now()-datetime.timedelta(minutes=10)][:6000]
    if len(distance_records_10min) < 6000:
        return
    distance_input = np.fromiter((record.distance for record in distance_records_10min), dtype=np.float32)
    distance_result = sukusute_machine_learning.inference.predict_distance.distance_infer(distance_input)

    distance_evalhist_stmt = select(sukusute_server.database_models.ChildDistanceEvaluationHistory) \
        .where(or_(
            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_1 == child_id,
            sukusute_server.database_models.ChildDistanceEvaluationHistory.child_id_2 == child_id,
        )) \
        .order_by(sukusute_server.database_models.ChildDistanceEvaluationHistory.date.asc())
    distance_evalhist_records = (await dbsession.execute(distance_evalhist_stmt)).scalars().all()
    relatedness_result = sukusute_machine_learning.utils.relatedness.calc_relatedness(
        record.evaluated for record in distance_evalhist_records
    )
    dbsession.add(sukusute_server.database_models.ChildDistanceEvaluationHistory(
        date=datetime.datetime.now(),
        evaluated=sukusute_server.database_models.ChildDistanceEvaluationEnum(distance_result["label"]),
        confidence=distance_result["confidence"],
        score=relatedness_result
    ))
    await dbsession.commit()

