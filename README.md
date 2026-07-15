# すくすてサーバ（prototype）
開発用として、SQliteを使っています。

## SQliteデータベースのマイグレート
既存の開発用DBをマイグレートする or 開発用DBを新規作成する場合
```
uv run alembic upgrade head
```

### マイグレートのためのリビジョンを作る
DBのテーブル定義を変更した時
```
uv run alembic revision --autogenerate
```

## サーバ実行（バックエンド + フロントエンド 一括起動）
`python -m sukusute_server` でバックエンドとフロントエンドを同時に起動します。

```
uv run python -m sukusute_server
```

- バックエンド: http://localhost:8000
- フロントエンド: http://localhost:3000

## ダミーデータ送信（20デバイスシミュレーション）
20デバイスをシミュレートし、歩数データと距離データを自動送信します。

```
uv run python dummy_data_sender.py
```

### 送信データ形式
- **歩数データ**: 累積値（1回あたり10-50歩、徐々に増加）
- **距離データ**: 2-60mの範囲で複数デバイス間の双方向距離
- **送信間隔**: デバイスごとに異なる（4-15秒）

### デバイス設定
各デバイスには以下の属性が設定されています:
- `device_id`: デバイスID（1-20）
- `interval`: 送信間隔（秒）
- `data_type`: データタイプ（steps, distance, both）
- `zone`: ゾーン名（東京各地）

## 児童データ管理（デバッグ用）

### 児童一覧表示
```
uv run python delete_children.py list
```

### すべての児童データを削除
```
uv run python delete_children.py delete_all
```

### 指定した児童データを削除
```
uv run python delete_children.py delete <child_id>
```

## APIエンドポイント

### データ受信
- `POST /api/push_data`: デバイスからデータを受信

**リクエスト形式:**
```json
{
  "child_id": 1,
  "singledata": {
    "date": "2026-07-15T10:00:00",
    "steps": 1234
  },
  "distances": [
    {
      "date": "2026-07-15T10:00:00",
      "with_child": 3,
      "distance": 0.035
    }
  ]
}
```

### データ取得
- `GET /api/health`: サーバヘルスチェック
- `GET /api/children`: 児童一覧取得
- `GET /api/children/{child_id}`: 特定児童のデータ取得
- `GET /api/children/{child_id}/steps`: 特定児童の歩数データ
- `GET /api/children/{child_id}/distances`: 特定児童の距離データ

## プロジェクト構造
```
sukusute_server/
├── sukusute_server/       # メインサーバーコード
│   ├── __init__.py        # FastAPIアプリケーション
│   ├── __main__.py        # サーバー起動スクリプト
│   ├── database_models.py # データベースモデル
│   └── http_models.py     # HTTPデータモデル
├── frontend/              # フロントエンド
│   ├── index.html
│   ├── app.js
│   └── style.css
├── migration/             # Alembicマイグレーション
├── dummy_data_sender.py   # ダミーデータ送信スクリプト
└── delete_children.py     # 児童データ削除スクリプト