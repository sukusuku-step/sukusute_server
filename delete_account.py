"""教師アカウントをユーザー名で削除するCLI。"""

import argparse
import asyncio

import sqlalchemy

from sukusute_server import database_models


async def delete_account(identifier: str) -> bool:
    async with database_models.AsyncSession(database_models.engine) as session:
        teacher = (await session.execute(
            sqlalchemy.select(database_models.Teacher).where(
                sqlalchemy.or_(
                    database_models.Teacher.username == identifier,
                    database_models.Teacher.name == identifier,
                )
            )
        )).scalar_one_or_none()
        if not teacher:
            return False
        await session.delete(teacher)
        await session.commit()
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="教師アカウントを削除します")
    parser.add_argument("identifier", help="削除するユーザー名または教師名")
    parser.add_argument(
        "--yes", action="store_true", help="確認プロンプトを省略する"
    )
    args = parser.parse_args()
    if not args.yes:
        answer = input(f"アカウント '{args.identifier}' を削除しますか？ [y/N]: ")
        if answer.strip().lower() != "y":
            print("キャンセルしました")
            return
    if asyncio.run(delete_account(args.identifier)):
        print("アカウントを削除しました")
    else:
        print("指定されたユーザーが見つかりません")


if __name__ == "__main__":
    main()