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

## サーバ実行
```
uv run python3 -m sukusute_server
```
