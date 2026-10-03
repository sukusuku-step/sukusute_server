""" データベースのテーブル定義など """
from __future__ import annotations

import datetime
import enum
import typing
import itertools
import pathlib
import uuid
import collections.abc

import fastapi
from sqlalchemy import ForeignKey, CheckConstraint, Tuple, select, SQLColumnExpression, or_
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, relationship, mapped_column
from sqlalchemy.sql.expression import tuple_

# プロジェクトルートのDBを常に参照する。起動ディレクトリに依存させない。
engine = create_async_engine(
        f"postgresql+asyncpg://sukusute:sukusute@127.0.0.1:5432/sukusute"
)


async def get_session():
    """各リクエストへ非同期SQLAlchemyセッションを注入する。"""
    async with AsyncSession(engine) as session:
        yield session

# SessionDep: FastAPIの依存性注入用型エイリアス
SessionDep: typing.TypeAlias = typing.Annotated[
    AsyncSession,
    fastapi.Depends(get_session)
]


# ===== ベースクラス =====

class Base(DeclarativeBase):
    pass


# ===== クラスモデル =====

class SchoolClass(Base):
    """クラス情報を管理するテーブル"""
    __tablename__ = "school_class"

    class_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
    # class_idを持つ児童を、クラス一覧から参照するための逆向きリレーション。
    children: Mapped[list[Child]] = relationship(back_populates="school_class")


# ===== 児童モデル =====

class Child(Base):
    """ 児童情報を管理するテーブル """
    __tablename__ = "child"

    child_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]
    device_id: Mapped[uuid.UUID]
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_class.class_id"), nullable=True
    )

    school_class: Mapped[SchoolClass | None] = relationship(
        back_populates="children"
    )

    # 単独データ（歩数など）
    singledata: Mapped[list[SingleChildData]] = relationship(
        back_populates="child"
    )

    # 距離データ（child_1として参加したもの）
    distance_1: Mapped[list[ChildDistanceData]] = relationship(
        back_populates="child_1",
        foreign_keys="ChildDistanceData.child_id_1"
    )
    # 距離データ（child_2として参加したもの）
    distance_2: Mapped[list[ChildDistanceData]] = relationship(
        back_populates="child_2",
        foreign_keys="ChildDistanceData.child_id_2"
    )

    @hybrid_property
    def distances(self) -> list[ChildDistanceData]:
        """child_id_1側・child_id_2側の距離データを一つにまとめて返す。"""
        return list(itertools.chain(self.distance_1, self.distance_2))

    @distances.inplace.expression
    @classmethod
    def _distances_expression(cls) -> SQLColumnExpression[list[ChildDistanceData]]:
        """SQLAlchemy検索時に両方向の距離レコードを選択する。"""
        return select(ChildDistanceData) \
            .where(or_(
                ChildDistanceData.child_id_1 == cls.child_id,
                ChildDistanceData.child_id_2 == cls.child_id
            )) \
            .label("distances")


# ===== 単独児童データモデル =====

class SingleChildData(Base):
    """ 子ども（単独）のデータを蓄積する（歩数など） """
    __tablename__ = "child_data"

    child_id: Mapped[int] = mapped_column(
        ForeignKey("child.child_id"),
        primary_key=True
    )
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)
    steps: Mapped[int] = mapped_column(primary_key=True)
    # 加速度(ax-ay-az)、ジャイロ(gx-gy-gz)、地磁気(mx-my-mz)の9軸データ。
    ax: Mapped[float]
    ay: Mapped[float]
    az: Mapped[float]
    gx: Mapped[float]
    gy: Mapped[float]
    gz: Mapped[float]
    mx: Mapped[float]
    my: Mapped[float]
    mz: Mapped[float]

    child: Mapped[Child] = relationship(foreign_keys=child_id)

# ===== 児童間距離データモデル =====
class HasTwoChildRelations():
    __table_args__ = (
        CheckConstraint("child_id_1 < child_id_2", name="child_id_order"),
    )
    @declared_attr
    def child_id_1(cls) -> Mapped[int]:
        return mapped_column(
            ForeignKey("child.child_id"),
            primary_key=True
        )
    @declared_attr
    def child_id_2(cls) -> Mapped[int]:
        return mapped_column(
            ForeignKey("child.child_id"),
            primary_key=True
        )

    @declared_attr
    def child_1(cls) -> Mapped[Child]:
        cls_ = typing.cast(type, cls)
        return relationship(foreign_keys=f"{cls_.__name__}.child_id_1")

    @declared_attr
    def child_2(cls) -> Mapped[Child]:
        cls_ = typing.cast(type, cls)
        return relationship(foreign_keys=f"{cls_.__name__}.child_id_2")

    @hybrid_property
    def children(self) -> tuple[Child, Child]:
        """ 両児童のタプルを返す """
        return (self.child_1, self.child_2)

    @children.inplace.setter
    def _children_setter(self, value: collections.abc.Iterable[Child]) -> None:
        """児童IDの大小で並べ、DBのchild_id_order制約を満たす。"""
        self.child_1 = min(value, key=lambda i: i.child_id)
        self.child_2 = max(value, key=lambda i: i.child_id)

    @hybrid_property
    def children_ids(self) -> tuple[int, int]:
        """ 両児童のchild_idのタプルを返す。 """
        return (self.child_id_1, self.child_id_2)

    @children_ids.inplace.setter
    def _children_ids_setter(self, value: collections.abc.Iterable[int]) -> None:
        self.child_id_1 = min(value)
        self.child_id_2 = max(value)

    @children_ids.inplace.expression
    @classmethod
    def _children_ids_radius_expression(cls) -> Tuple:
        return tuple_(cls.child_id_1, cls.child_id_2)


class ChildDistanceData(HasTwoChildRelations, Base):
    """ 子ども同士の距離データを蓄積する
    
    注意: child_id_1 < child_id_2 となるように制約を設定する。
    送信方向に依存せず、同じ児童ペアを一意に扱うための並び順。
    """
    __tablename__ = "child_distance"

    distance: Mapped[float]
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)

# ===== 評価結果の保存 =====

class ChildDistanceEvaluationEnum(enum.Enum):
    """ 相対距離の評価結果 """
    NA = "測定値なし/タイムアウト"
    ALONE = "一人"
    SAME_BEHAVIOR = "接近（同じ部屋）"
    SAME_ROOM = "接近（同じ行動）"

class ChildDistanceEvaluationHistory(HasTwoChildRelations, Base):
    """ 相対距離についての推論結果の履歴を保存するテーブル """
    __tablename__ = "child_distance_evalhist"
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)
    evaluated: Mapped[ChildDistanceEvaluationEnum]
    confidence: Mapped[float]
    score: Mapped[float]

class ChildBehaviorPedoEnum(enum.Enum):
    SLOW = "歩行（ゆっくり）"
    NORMAL = "歩行（通常速度）"
    STOP = "静止"
class ChildBehaviorAcceEnum(enum.Enum):
    SITTING = "座り状態"
    STANDING = "立ち状態"

class ChildBehaviorDataEvaluationHistory(Base):
    __tablename__ = "behaivor_evalhist"

    child_id: Mapped[int] = mapped_column(
        ForeignKey("child.child_id"),
        primary_key=True
    )
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)
    behavior_acce: Mapped[ChildBehaviorAcceEnum]
    behavior_acce_confidence: Mapped[float]
    behavior_pedo: Mapped[ChildBehaviorPedoEnum]
    behavior_pedo_confidence: Mapped[float]
    activity: Mapped[int]
    activity_confidence: Mapped[float]

    baseline_steps_10min_median: Mapped[typing.Optional[float]]
    baseline_steps_10min_mad_scale: Mapped[typing.Optional[float]]
    baseline_activity_mean_proxy_median: Mapped[typing.Optional[float]]
    baseline_activity_mean_proxy_mad_scale: Mapped[typing.Optional[float]]
    baseline_acc_std_median: Mapped[typing.Optional[float]]
    baseline_acc_std_mad_scale: Mapped[typing.Optional[float]]
    baseline_gyro_mean_median: Mapped[typing.Optional[float]]
    baseline_gyro_mean_mad_scale: Mapped[typing.Optional[float]]
    baseline_mag_mean_median: Mapped[typing.Optional[float]]
    baseline_mag_mean_mad_scale: Mapped[typing.Optional[float]]

    child: Mapped[Child] = relationship(foreign_keys=child_id)

# ===== 教師モデル =====

class Teacher(Base):
    """ 教師情報を管理するテーブル """
    __tablename__ = "teacher"

    username: Mapped[str] = mapped_column(primary_key=True)
    pw_hash: Mapped[bytes]
    name: Mapped[str]

# ===== 設定 =====
class Settings(Base):
    """ 設定情報を管理するテーブル """
    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("_ = 1", name="no_multiple_config"),
    )

    _: Mapped[bool] = mapped_column(primary_key=True, default=1)
    activity_max_data_minutes: Mapped[int]
    anomaly_threshold_ratio: Mapped[float]
    baseline_min_data_minutes: Mapped[int]
    baseline_max_days: Mapped[int]
    relatedness_max_history: Mapped[int]
    relatedness_max_steps_minutes: Mapped[int]

