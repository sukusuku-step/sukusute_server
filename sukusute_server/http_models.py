""" FastAPI エンドポイント用データモデル定義 """

import typing
import datetime
import uuid

import pydantic

from sukusute_server import database_models


# ===== 共通レスポンスと認証・クラス管理 =====

class Result(pydantic.BaseModel):
    """ エンドポイントの結果 """
    status: typing.Literal["ok", "error"]
    msg: typing.Optional[str] = None


class LoginRequest(pydantic.BaseModel):
    username: str
    password: str


class RegisterRequest(LoginRequest):
    pass


class LoginResponse(Result):
    token: str
    username: str
    name: str


class ClassCreateRequest(pydantic.BaseModel):
    name: str


class ClassItem(pydantic.BaseModel):
    class_id: int
    name: str
    child_count: int


class ClassListResponse(Result):
    classes: list[ClassItem]


class ClassResponse(Result):
    class_id: int
    name: str


class ChildClassRequest(pydantic.BaseModel):
    class_id: typing.Optional[int] = None


# ===== デバイスから受信する児童データ =====

class ChildSingleData(pydantic.BaseModel):
    """ 単独の児童についてのデータ（歩数など） """
    date: datetime.datetime = pydantic.Field(default_factory=datetime.datetime.now)
    steps: int


class ChildDistanceData(pydantic.BaseModel):
    """ 児童の距離データ """
    date: datetime.datetime = pydantic.Field(default_factory=datetime.datetime.now)
    with_child: int
    distance: float


class ChildDataRecord(pydantic.BaseModel):
    """ デバイスからの受信データ """
    child_id: int
    singledata: typing.Optional[ChildSingleData] = None
    distances: typing.Optional[list[ChildDistanceData]] = None

    model_config = pydantic.ConfigDict(extra="ignore")


class ChildDataResponse(Result):
    """ 児童のすべての情報を含むレスポンス """
    child_id: int
    name: str
    device_id: uuid.UUID
    singledata: list[ChildSingleData]
    distancedata: list[ChildDistanceData]


class ChildSearchResponse(Result):
    """ 児童名から検索した結果を含むレスポンス """
    child_id: int
    name: str


class DeviceStatusRequest(pydantic.BaseModel):
    """M5から受信する最新の端末状態"""
    child_id: int = pydantic.Field(gt=0)
    battery: int = pydantic.Field(ge=0, le=100)
    wifi_rssi: int = pydantic.Field(ge=-127, le=0)


class DeviceStatus(pydantic.BaseModel):
    """メモリ上に保持する端末状態"""
    child_id: int
    battery: int
    wifi_rssi: int
    updated_at: datetime.datetime


class DeviceStatusListResponse(Result):
    devices: list[DeviceStatus]


# ===== 児童一覧 =====

class ChildListItem(pydantic.BaseModel):
    """ 児童一覧の項目 """
    child_id: int
    name: str
    device_id: uuid.UUID
    class_id: typing.Optional[int] = None


class ChildrenListResponse(Result):
    """ 児童一覧レスポンス """
    children: list[ChildListItem]


# ===== 歩数と警告 =====

class StepsByHour(pydantic.BaseModel):
    """ 時間別歩数 """
    hour: int
    steps: int


class DailySteps(pydantic.BaseModel):
    """ 日別歩数 """
    date: datetime.datetime
    steps: int


class StepWarning(pydantic.BaseModel):
    """ 歩数警告 - 普段の平均に対する歩数が少ない児童 """
    child_id: int
    name: str
    current_steps: int
    average_steps: int
    percent: int  # 普段の平均に対する割合(%)
    date: datetime.datetime


class ChildStepsResponse(Result):
    """ 特定児童の歩数レスポンス """
    child_id: int
    name: str
    device_id: uuid.UUID
    date: datetime.datetime
    steps: int
    steps_by_hour: list[StepsByHour]
    history: typing.Optional[list[DailySteps]] = None
    previous_day_steps: int
    step_change_percent: float
    walk_time: int
    calories: int
    goal_met: bool


class ChildStepsHistoryResponse(Result):
    """ 特定児童の歩数履歴レスポンス """
    child_id: int
    name: str
    history: list[DailySteps]


# ===== 児童間距離と集計 =====

class ChildDistance(pydantic.BaseModel):
    """ 児童の距離データ """
    with_child: int
    other_name: typing.Optional[str] = None
    distance: float
    date: datetime.datetime


class DistanceStat(pydantic.BaseModel):
    """ 距離統計（最大/最小） """
    with_child: int
    distance: float


class StudentDistanceStat(pydantic.BaseModel):
    """ 児童別距離統計 """
    child_id: int
    name: str
    total_distance: float
    avg_distance: float
    meeting_count: int


class PairDistance(pydantic.BaseModel):
    """ ペア別距離 """
    child_id_1: int
    child_id_2: int
    name1: str
    name2: str
    distance: float


class ChildDistancesResponse(Result):
    """ 特定児童の距離データレスポンス """
    child_id: int
    name: str
    device_id: uuid.UUID
    date: datetime.datetime
    distances: list[ChildDistance]
    total_distance: float
    avg_distance: float
    max_distance: typing.Optional[DistanceStat] = None
    min_distance: typing.Optional[DistanceStat] = None
    meeting_count: int


class DistanceStatsResponse(Result):
    """ 距離データ集計レスポンス """
    date: datetime.datetime
    total_distance: float
    meeting_count: int
    avg_distance: float
    student_stats: list[StudentDistanceStat]
    top_pairs: list[PairDistance]


# ===== 全体集計 =====

class StudentRankingItem(pydantic.BaseModel):
    """ 児童ランキング項目 """
    child_id: int
    name: str
    steps: int


class StepIncreaseRankingItem(pydantic.BaseModel):
    """1分間の歩数増加ランキング項目"""
    child_id: int
    name: str
    increase_steps: int


class NearestChild(pydantic.BaseModel):
    """指定日の最新距離で最も近い相手"""
    child_id: int
    name: str
    distance: float


class TodayStatsResponse(Result):
    """ 今日の集計情報レスポンス """
    date: datetime.datetime
    total_steps: int
    avg_steps: int
    walk_time: int
    calories: int
    goal_met_count: int
    total_students: int
    step_change: int
    step_change_percent: float
    steps_by_hour: list[StepsByHour]
    student_ranking: list[StudentRankingItem]
    step_increase_ranking: list[StepIncreaseRankingItem] = pydantic.Field(default_factory=list)
    nearest_children: list[NearestChild] = pydantic.Field(default_factory=list)
    warnings: list[StepWarning]


class MonthlyStatsResponse(Result):
    """ 月間集計情報レスポンス """
    year: int
    month: int
    total_steps: int
    total_distance: float
    remaining_days: int
    last_day: int

class MLSingleResult(Result):
    """ 単独児童の推論結果レスポンス"""
    date: datetime.datetime
    behavior_acce: database_models.ChildBehaviorAcceEnum
    behavior_acce_confidence: float
    behavior_pedo: database_models.ChildBehaviorPedoEnum
    behavior_pedo_confidence: float
    activity_level: int
    activity_confidence: float

    baseline_steps_10min_median: typing.Optional[float]
    baseline_steps_10min_mad_scale: typing.Optional[float]
    baseline_activity_mean_proxy_median: typing.Optional[float]
    baseline_activity_mean_proxy_mad_scale: typing.Optional[float]
    baseline_acc_std_median: typing.Optional[float]
    baseline_acc_std_mad_scale: typing.Optional[float]
    baseline_gyro_mean_median: typing.Optional[float]
    baseline_gyro_mean_mad_scale: typing.Optional[float]
    baseline_mag_mean_median: typing.Optional[float]
    baseline_mag_mean_mad_scale: typing.Optional[float]

class MLRelationResult(Result):
    date: datetime.datetime
    evaluated: database_models.ChildDistanceEvaluationEnum
    confidence: float
    score: float
