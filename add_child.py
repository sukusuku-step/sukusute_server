import asyncio
import uuid
import sqlalchemy
import sqlalchemy.ext.asyncio
from sukusute_server import database_models

engine = sqlalchemy.ext.asyncio.create_async_engine("sqlite+aiosqlite:///data.sqlite")

async def add_child():
    async with sqlalchemy.ext.asyncio.AsyncSession(engine) as session:
        child = database_models.Child(name="test", device_id=uuid.uuid4())
        session.add(child)
        await session.commit()

if __name__ == "__main__":
    asyncio.run(add_child())

