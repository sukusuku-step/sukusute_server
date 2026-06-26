""" FastAPI エンドポイント用データモデル定義 """

import typing
import datetime
import uuid

import pydantic

class Result(pydantic.BaseModel):
    """ 通常エンドポイントの結果 """
    status: typing.Literal["ok", "error"]
    msg: typing.Optional[str] = None

class ChildSingleData(pydantic.BaseModel):
    """ 単独の児童についてのデータ """
    date: datetime.datetime
    steps: int

class ChildDistanceData(pydantic.BaseModel):
    """ 児童の距離についてのデータ """
    date: datetime.datetime
    with_child: int
    distance: float

class ChildDataRecord(pydantic.BaseModel):
    """ デバイスからの受信データ """
    child_id: int
    singledata: typing.Optional[ChildSingleData]
    distances: typing.Optional[list[ChildDistanceData]]

class ChildDataResponse(Result):
    """ Childに対するすべての情報 """
    child_id: int
    name: str
    device_id: uuid.UUID
    singledata: list[ChildSingleData]
    distancedata: list[ChildDistanceData]
