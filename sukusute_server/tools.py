import datetime

from sqlalchemy import select
from sqlalchemy.sql.functions import count
from sukusute_server import database_models

async def child_total_time(dbsession: database_models.SessionDep, child_id: int) -> datetime.timedelta:
    """ 児童について、累計何秒間計測したかを計算"""
    stmt = select(count()).select_from(database_models.SingleChildData).where(database_models.SingleChildData.child_id == child_id)
    res = (await dbsession.execute(stmt)).scalar()
    return datetime.timedelta(seconds=(res or 0)*.1)

