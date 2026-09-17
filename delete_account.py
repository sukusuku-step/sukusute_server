"""教師アカウントをパスワード確認付きで削除するCLI。"""

import argparse
import asyncio
import getpass

from sukusute_server import database_models
from sukusute_server import verify_password


async def delete_account(username: str, password: str) -> bool:
    async with database_models.AsyncSession(database_models.engine) as session:
        teacher = await session.get(database_models.Teacher, username)
        if not teacher or not verify_password(password, teacher.pw_hash):
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
    password = getpass.getpass("パスワード: ")
    if asyncio.run(delete_account(args.username, password)):
        print("アカウントを削除しました")
    else:
        print("ユーザー名またはパスワードが違います")


if __name__ == "__main__":
    main()