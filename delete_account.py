"""教師アカウントをユーザー名で削除するCLI。"""

import argparse
import asyncio

from sukusute_server import database_models


async def delete_account(username: str) -> bool:
    async with database_models.AsyncSession(database_models.engine) as session:
        teacher = await session.get(database_models.Teacher, username)
        if not teacher:
            return False
        await session.delete(teacher)
        await session.commit()
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="教師アカウントを削除します")
    parser.add_argument("username", help="削除するユーザー名")
    parser.add_argument(
        "--yes", action="store_true", help="確認プロンプトを省略する"
    )
    args = parser.parse_args()
    if not args.yes:
        answer = input(f"アカウント '{args.username}' を削除しますか？ [y/N]: ")
        if answer.strip().lower() != "y":
            print("キャンセルしました")
            return
    if asyncio.run(delete_account(args.username)):
        print("アカウントを削除しました")
    else:
        print("指定されたユーザーが見つかりません")


if __name__ == "__main__":
    main()