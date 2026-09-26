""" HTTPサーバの起動 (バックエンド + フロントエンド) """

import os


def run_backend(host: str = "0.0.0.0", port: int = 8000):
    """サーバを起動"""
    try:
        import uvicorn
        import sukusute_server
        print(f"サーバを起動中... http://{host}:{port}")
        uvicorn.run(sukusute_server.app, host=host, port=port, access_log=False)
    except ImportError as e:
        print(f"起動エラー: 依存関係がインストールされていません - {e}")
        print("pyproject.tomlの依存関係をインストールしてください:")
        print("  uv sync")
    except Exception as e:
        print(f"エラー: {e}")

def main():
    """環境変数から起動先を読み、バックエンドを開始する。"""
    host = os.getenv("SUKUSUTE_HOST", "0.0.0.0")
    port = int(os.getenv("SUKUSUTE_PORT", "8000"))
    run_backend(host, port)

if __name__ == "__main__":
    main()
