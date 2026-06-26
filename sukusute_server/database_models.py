""" データベースのテーブル定義など """
from __future__ import annotations

import datetime
import typing
import collections.abc
import itertools
import uuid

import fastapi
from sqlalchemy import ForeignKey, CheckConstraint, select, SQLColumnExpression, or_
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship, mapped_column

engine = create_async_engine("sqlite+aiosqlite:///data.sqlite")

async def get_session():
    """ (FastAPI用) セッションを作成 """
    async with AsyncSession(engine) as session:
        yield session
SessionDep: typing.TypeAlias = typing.Annotated[AsyncSession, fastapi.Depends(get_session)]

# pylint: disable=R0903 C0115

class Base(DeclarativeBase):
    pass

class Child(Base):
    __tablename__ = "child"

    child_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]
    device_id: Mapped[uuid.UUID]

    singledata: Mapped[list[SingleChildData]] = relationship(back_populates="child")

    distance_1: Mapped[list[ChildDistanceData]] = relationship(
        back_populates="child_1",
        foreign_keys="ChildDistanceData.child_id_1"
    )
    distance_2: Mapped[list[ChildDistanceData]] = relationship(
        back_populates="child_2",
        foreign_keys="ChildDistanceData.child_id_2"
    )

    @hybrid_property
    def distances(self) -> list[ChildDistanceData]: #pylint: disable=C0116
        return list(itertools.chain(self.distance_1, self.distance_2))

    @distances.inplace.expression
    @classmethod
    def _distances_expression(cls) -> SQLColumnExpression[list[ChildDistanceData]]:
        return select(ChildDistanceData) \
            .where(or_(ChildDistanceData.child_id_1==cls.child_id,
                       ChildDistanceData.child_id_2==cls.child_id)) \
            .label("distances")

class SingleChildData(Base):
    """ 子ども（単独）のデータを蓄積する。 """
    __tablename__ = "child_data"

    child_id: Mapped[int] = mapped_column(ForeignKey("child.child_id"), primary_key=True)
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)
    steps: Mapped[int] = mapped_column(primary_key=True)

    child: Mapped[Child] = relationship(foreign_keys=child_id)

class ChildDistanceData(Base):
    """ 子ども同士の距離データを蓄積する。child_1.child_id < child_2.child_idに注意！ """
    __tablename__ = "child_distance"
    __table_args__ = (
        CheckConstraint("child_id_1 < child_id_2", name="child_id_order"),
    )

    child_id_1: Mapped[int] = mapped_column(ForeignKey("child.child_id"), primary_key=True)
    child_id_2: Mapped[int] = mapped_column(ForeignKey("child.child_id"), primary_key=True)
    distance: Mapped[float]
    date: Mapped[datetime.datetime] = mapped_column(primary_key=True)

    child_1: Mapped[Child] = relationship(foreign_keys=child_id_1)
    child_2: Mapped[Child] = relationship(foreign_keys=child_id_2)

    @hybrid_property
    def children(self) -> tuple[Child]: #pylint: disable=C0116
        return (self.child_1, self.child_2)

    @children.inplace.setter
    def _children_setter(self, value: collections.abc.Iterable[Child]) -> None:
        self.child_1 = min(value, key=lambda i: i.child_id)
        self.child_2 = max(value, key=lambda i: i.child_id)

    @children.inplace.expression
    @classmethod
    def _radius_expression(cls) -> SQLColumnExpression[tuple[Child]]:
        return select(Child) \
            .where(or_(Child.child_id==cls.child_1, Child.child_id==cls.child_2)) \
            .label("children")

class Teacher(Base):
    __tablename__ = "teacher"

    username: Mapped[str] = mapped_column(primary_key=True)
    pw_hash: Mapped[bytes]
    name: Mapped[str]
