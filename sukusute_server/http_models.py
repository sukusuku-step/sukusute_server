""" FastAPI エンドポイント用データモデル定義 """

import typing
import datetime
import uuid

import pydantic


# ===== 基本モデル =====

class Result(pydantic.BaseModel):
    """ エンドポイントの結果 """
    status: typing.Literal["ok", "error"]
    msg: typing.Optional[str] = None


# ===== 児童データモデル =====

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


# ===== 児童一覧モデル =====

class ChildListItem(pydantic.BaseModel):
    """ 児童一覧の項目 """
    child_id: int
    name: str
    device_id: uuid.UUID


class ChildrenListResponse(Result):
    """ 児童一覧レスポンス """
    children: list[ChildListItem]


# ===== 歩数データモデル =====

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


# ===== 距離データモデル =====

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


# ===== 集計情報モデル =====

class StudentRankingItem(pydantic.BaseModel):
    """ 児童ランキング項目 """
    child_id: int
    name: str
    steps: int


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
    warnings: list[StepWarning]


class MonthlyStatsResponse(Result):
    """ 月間集計情報レスポンス """
    year: int
    month: int
    total_steps: int
    total_distance: float
    remaining_days: int
    last_day: int
