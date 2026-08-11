""" HTTPサーバの起動 (バックエンド + フロントエンド) """

def run_backend(port: int = 8000):
    """サーバを起動"""
    try:
        import uvicorn
        import sukusute_server
        print(f"サーバを起動中... http://localhost:{port}")
        uvicorn.run(sukusute_server.app, host="0.0.0.0", port=port)
    except ImportError as e:
        print(f"起動エラー: 依存関係がインストールされていません - {e}")
        print("pyproject.tomlの依存関係をインストールしてください:")
        print("  uv sync")
    except Exception as e:
        print(f"エラー: {e}")

def main():
    run_backend(8000)

if __name__ == "__main__":
    main()
