""" HTTPサーバの起動 (バックエンド + フロントエンド) """
import os
import sys
import threading
import time


def run_frontend(port: int = 3000):
    """フロントエンドサーバを起動"""
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    print(f"[フロントエンド] サーバを起動中... http://localhost:{port}")
    try:
        import http.server
        import socketserver
        
        os.chdir(frontend_dir)
        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
            print(f"[フロントエンド] http://localhost:{port} でサーバーを実行中...")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("[フロントエンド] サーバを停止しました")
    except Exception as e:
        print(f"[フロントエンド] エラー: {e}")


def run_backend(port: int = 8000):
    """バックエンドサーバを起動"""
    try:
        import uvicorn
        import sukusute_server
        print(f"[バックエンド] サーバを起動中... http://localhost:{port}")
        uvicorn.run(sukusute_server.app, host="0.0.0.0", port=port)
    except ImportError as e:
        print(f"[バックエンド] 起動エラー: 依存関係がインストールされていません - {e}")
        print("[バックエンド] pyproject.tomlの依存関係をインストールしてください:")
        print("  uv sync")
        print("  または: pip install fastapi uvicorn sqlalchemy pydantic alembic")
    except Exception as e:
        print(f"[バックエンド] エラー: {e}")


def main():
    """メイン関数 - バックエンドとフロントエンドを同時に起動"""
    # フロントエンドをバックグラウンドスレッドで起動
    frontend_thread = threading.Thread(target=run_frontend, args=(3000,), daemon=True)
    frontend_thread.start()
    time.sleep(1)  # フロントエンドの起動を待つ
    
    # バックエンドをメインスレッドで起動
    run_backend(8000)


if __name__ == "__main__":
    main()
