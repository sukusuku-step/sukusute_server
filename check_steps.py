""" データベースの歩数データを確認 """
import asyncio
from sqlalchemy import select, text
from sukusute_server import database_models

async def check():
    async with database_models.engine.begin() as conn:
        # 日付降順で最新のデータを取得
        result = await conn.execute(
            select(database_models.SingleChildData)
            .order_by(database_models.SingleChildData.child_id, text("date DESC"))
            .limit(30)
        )
        rows = result.all()
        print("最新の歩数データ:")
        for r in rows:
            print(f"  child_id={r.child_id}, steps={r.steps}, date={r.date}")
        
        # child_idごとの最新のステップをグループ化
        print("\nchild_idごとの最新データ:")
        latest = {}
        for r in rows:
            if r.child_id not in latest:
                latest[r.child_id] = r
        for child_id in sorted(latest.keys()):
            r = latest[child_id]
            print(f"  child_id={r.child_id}, steps={r.steps}, date={r.date}")

if __name__ == "__main__":
    asyncio.run(check())
