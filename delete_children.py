"""
児童データ削除スクリプト（デバッグ用）

データベースから児童データを削除します。
"""

import asyncio
import sys
import sqlalchemy
from sukusute_server import database_models


async def delete_all_children():
    """すべての児童データを削除"""
    async with database_models.engine.begin() as conn:
        # 削除前の児童一覧
        result = await conn.execute(sqlalchemy.select(database_models.Child))
        children = result.all()
        print(f"削除対象の児童数: {len(children)}")
        for c in children:
            print(f"  child_id={c.child_id}, name={c.name}, device_id={c.device_id}")
        
        # 児童データを削除
        await conn.execute(sqlalchemy.delete(database_models.SingleChildData))
        await conn.execute(sqlalchemy.delete(database_models.ChildDistanceData))
        await conn.execute(sqlalchemy.delete(database_models.Child))
        
        print(f"✅ {len(children)}人の児童データを削除しました")


async def delete_child_by_id(child_id: int):
    """指定したchild_idの児童データを削除"""
    async with database_models.engine.begin() as conn:
        # 対象児童を取得
        result = await conn.execute(
            sqlalchemy.select(database_models.Child).where(database_models.Child.child_id == child_id)
        )
        child = result.scalar()
        
        if not child:
            print(f"❌ child_id={child_id}の児童は存在しません")
            return
        
        print(f"削除対象: child_id={child.child_id}, name={child.name}")
        
        # 関連データを削除
        await conn.execute(
            sqlalchemy.delete(database_models.SingleChildData).where(database_models.SingleChildData.child_id == child_id)
        )
        await conn.execute(
            sqlalchemy.delete(database_models.ChildDistanceData).where(
            sqlalchemy.or_(
                database_models.ChildDistanceData.child_id_1 == child_id,
                database_models.ChildDistanceData.child_id_2 == child_id
            )
        ))
        await conn.execute(
            sqlalchemy.delete(database_models.Child).where(database_models.Child.child_id == child_id)
        )
        
        print(f"✅ child_id={child_id}の児童データを削除しました")


async def list_children():
    """児童一覧を表示"""
    async with database_models.engine.begin() as conn:
        result = await conn.execute(
            sqlalchemy.select(database_models.Child).order_by(database_models.Child.child_id)
        )
        children = result.all()
        
        print(f"児童数: {len(children)}")
        for c in children:
            # 歩数データ数をカウント
            steps_result = await conn.execute(
                sqlalchemy.select(sqlalchemy.func.count()).where(database_models.SingleChildData.child_id == c.child_id)
            )
            steps_count = steps_result.scalar()
            
            # 距離データ数をカウント
            dist_result = await conn.execute(
                sqlalchemy.select(sqlalchemy.func.count()).where(
                    sqlalchemy.or_(
                        database_models.ChildDistanceData.child_id_1 == c.child_id,
                        database_models.ChildDistanceData.child_id_2 == c.child_id
                    )
                )
            )
            dist_count = dist_result.scalar()
            
            print(f"  child_id={c.child_id}, name={c.name}, device_id={c.device_id}, steps={steps_count}, distances={dist_count}")


def main():
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python delete_children.py list          - 児童一覧を表示")
        print("  python delete_children.py delete_all    - すべての児童データを削除")
        print("  python delete_children.py delete <id>   - 指定したchild_idの児童データを削除")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        asyncio.run(list_children())
    elif command == "delete_all":
        confirm = input("すべての児童データを削除します。よろしいですか？(y/N): ")
        if confirm.lower() == "y":
            asyncio.run(delete_all_children())
        else:
            print("キャンセルしました")
    elif command == "delete":
        if len(sys.argv) < 3:
            print("child_idを指定してください")
            sys.exit(1)
        child_id = int(sys.argv[2])
        asyncio.run(delete_child_by_id(child_id))
    else:
        print(f"未知のコマンド: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()