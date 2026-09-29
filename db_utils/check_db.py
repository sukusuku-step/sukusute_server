"""データベース確認スクリプト"""
import asyncio
import sqlalchemy
from sukusute_server import database_models

async def check_db():
    async with database_models.engine.begin() as conn:
        # テーブル一覧
        result = await conn.execute(sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = result.fetchall()
        print('テーブル一覧:', [t[0] for t in tables])
        
        # childテーブルのデータ
        result = await conn.execute(sqlalchemy.select(database_models.Child))
        children = result.all()
        print(f'児童数: {len(children)}')
        for c in children:
            print(f'  child_id={c.child_id}, name={c.name}, device_id={c.device_id}')
        
        # singledataテーブルのデータ
        result = await conn.execute(sqlalchemy.select(database_models.SingleChildData))
        steps = result.all()
        print(f'歩数データ数: {len(steps)}')
        for s in steps[:5]:
            print(f'  child_id={s.child_id}, date={s.date}, steps={s.steps}')
        
        # distanceテーブルのデータ
        result = await conn.execute(sqlalchemy.select(database_models.ChildDistanceData))
        distances = result.all()
        print(f'距離データ数: {len(distances)}')
        for d in distances[:5]:
            print(f'  child_id_1={d.child_id_1}, child_id_2={d.child_id_2}, distance={d.distance}, date={d.date}')

if __name__ == "__main__":
    asyncio.run(check_db())