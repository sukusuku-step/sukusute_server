import asyncio
import uuid
import sqlalchemy
import sqlalchemy.ext.asyncio
import sys
from sukusute_server import database_models

engine = sqlalchemy.ext.asyncio.create_async_engine("sqlite+aiosqlite:///data.sqlite")

async def add_child(child_id: int, name: str):
    async with sqlalchemy.ext.asyncio.AsyncSession(engine) as session:
        child = database_models.Child(child_id=child_id, name=name, device_id=uuid.uuid4())
        session.add(child)
        await session.commit()

if __name__ == "__main__":
    child_id, name = sys.argv[1:3]
    asyncio.run(add_child(int(child_id), name))

