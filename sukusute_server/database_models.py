""" データベースのテーブル定義など """
from __future__ import annotations

import datetime
import typing
import collections.abc
import itertools
import pathlib
import uuid

import fastapi
from sqlalchemy import ForeignKey, CheckConstraint, select, SQLColumnExpression, or_
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship, mapped_column

# プロジェクトルートのDBを常に参照する。起動ディレクトリに依存させない。
DATABASE_PATH = pathlib.Path(__file__).resolve().parent.parent / "data.sqlite"
engine = create_async_engine(
    f"sqlite+aiosqlite:///{DATABASE_PATH.as_posix()}"
)


async def get_session():
    """ (FastAPI用) セッションを作成 """
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
        """ 両方の距離データを結合して返す """
        return list(itertools.chain(self.distance_1, self.distance_2))

    @distances.inplace.expression
    @classmethod
    def _distances_expression(cls) -> SQLColumnExpression[list[ChildDistanceData]]:
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

    child: Mapped[Child] = relationship(foreign_keys=child_id)


# ===== 児童間距離データモデル =====

class ChildDistanceData(Base):
    """ 子ども同士の距離データを蓄積する
    
    注意: child_1.child_id < child_id_2 となるように制約を設定
    """
    __tablename__ = "child_distance"
    __table_args__ = (
        CheckConstraint("child_id_1 < child_id_2", name="child_id_order"),
    )

    child_id_1: Mapped[int] = mapped_column(
        ForeignKey("child.child_id"),
        primary_key=True
    )
    child_id_2: Mapped[int] = mapped_column(
        ForeignKey("child.child_id"),
        primary_key=True
    )
    distance: Mapped[float]
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)

    child_1: Mapped[Child] = relationship(foreign_keys=child_id_1)
    child_2: Mapped[Child] = relationship(foreign_keys=child_id_2)

    @hybrid_property
    def children(self) -> tuple[Child]:
        """ 両児童のタプルを返す """
        return (self.child_1, self.child_2)

    @children.inplace.setter
    def _children_setter(self, value: collections.abc.Iterable[Child]) -> None:
        """ 児童セット - IDの大小に基づいてchild_1, child_2を自動設定 """
        self.child_1 = min(value, key=lambda i: i.child_id)
        self.child_2 = max(value, key=lambda i: i.child_id)

    @children.inplace.expression
    @classmethod
    def _radius_expression(cls) -> SQLColumnExpression[tuple[Child]]:
        return select(Child) \
            .where(or_(
                Child.child_id == cls.child_1,
                Child.child_id == cls.child_2
            )) \
            .label("children")


# ===== 教師モデル =====

class Teacher(Base):
    """ 教師情報を管理するテーブル """
    __tablename__ = "teacher"

    username: Mapped[str] = mapped_column(primary_key=True)
    pw_hash: Mapped[bytes]
    name: Mapped[str]