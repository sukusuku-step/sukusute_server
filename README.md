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
- フロントエンド: http://localhost:8080

## ダミーデータ送信
```
uv run python dummy_data_sender.py