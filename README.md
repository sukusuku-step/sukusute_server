# すくすてサーバ（prototype）

児童の歩数と児童間の距離を受信・集計するFastAPIサーバです。開発環境ではSQLite（`data.sqlite`）を使います。

## 必要な環境

- Python 3.14以上
- [uv](https://docs.astral.sh/uv/)（依存関係と実行に使用）

## セットアップと起動

```sh
uv sync
uv run alembic upgrade head
uv run python -m sukusute_server
```

バックエンドは `http://localhost:8000` で起動します。APIドキュメントは [http://localhost:8000/docs](http://localhost:8000/docs)、ReDocは [http://localhost:8000/redoc](http://localhost:8000/redoc) で確認できます。`frontend/` の画面も同じアプリから配信されるため、[http://localhost:8000/](http://localhost:8000/) を開いてください。

### マイグレーション

既存DBを最新スキーマに更新する場合、またはDBを新規作成する場合:

```sh
uv run alembic upgrade head
```

テーブル定義を変更して新しいリビジョンを作る場合:

```sh
uv run alembic revision --autogenerate -m "変更内容"
```

## API共通仕様

- ベースURL: `http://localhost:8000`
- JSONの日時はISO 8601形式（例: `2026-07-15T10:00:00`）です。タイムゾーンなしの日時として扱います。
- 成功レスポンスには原則 `status: "ok"` が含まれます。
- リクエスト形式が不正な場合はFastAPIの `422 Unprocessable Entity`、対象児童がない場合は `404 Not Found` です。
- 距離の単位はkmです。例えば2-60mは `0.002-0.060` で送ります。

## API一覧

### ヘルスチェック

#### `GET /api/health`

サーバが応答できれば、次を返します。

```json
{"status": "ok", "msg": null}
```

### データ送信

#### `POST /api/push_data`

指定した児童の歩数、または児童間距離を保存します。`singledata` と `distances` はどちらも任意ですが、両方省略すると何も保存せず成功します。未知のフィールドは無視されます。

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

`child_id` が存在しない場合は `404` です。距離データの `with_child` が存在しない場合、その距離レコードだけ警告ログを出して無視し、リクエスト全体は成功します。保存時には児童IDの大小を並べ替えるため、送信方向が逆でも同じ児童ペアとして扱われます。

成功時:

```json
{"status": "ok", "msg": null}
```

### 児童管理

#### `GET /api/children`

登録済み児童を `child_id` 順に返します。

```json
{
  "status": "ok",
  "children": [
    {"child_id": 1, "name": "太郎", "device_id": "uuid"}
  ]
}
```

#### `GET /api/children/search?name=太郎`

名前が完全一致する児童を検索します。該当者がいない場合は、その名前の児童を新規作成してIDを返します。したがって、このAPIは検索だけでなく児童登録にも使われます。

```json
{"status": "ok", "child_id": 1, "name": "太郎"}
```

#### `GET /api/children/{child_id}`

児童の基本情報、保存済みの歩数レコード（`singledata`）、距離レコード（`distancedata`）をすべて返します。児童がなければ `404` です。

#### `POST /api/create_debug_child`

デバッグ用に名前 `Test Child` の児童を1件作成します。重複チェックはありません。ダミーデータ送信前のテストデータ作成に使います。

成功時は `{"status": "ok", "msg": null}` です。

### 歩数

#### `GET /api/children/{child_id}/steps?year=2026&month=7&day=15`

指定日の最新歩数レコードを返します。`year`、`month`、`day` を省略すると、サーバ起動プロセスの現在日時を使います。データがない日は `steps: 0` です。

レスポンスには次が含まれます。

- `steps`: 指定日の最新歩数
- `previous_day_steps`: 前日の最新歩数
- `step_change_percent`: 前日比（前日が0の場合は0）
- `walk_time`: `steps / 150` の整数分
- `calories`: `steps * 0.008` の整数値
- `goal_met`: 10,000歩以上なら `true`
- `history`: 指定日を含む過去7日分。データがない日は0
- `steps_by_hour`: 現在は常に空配列

#### `GET /api/children/{child_id}/steps/history?days=7`

現在日から過去に向かって、`days` 日分の歩数を返します。`days` のデフォルトは7です。データがない日は0になります。

```json
{
  "status": "ok",
  "child_id": 1,
  "name": "太郎",
  "history": [
    {"date": "2026-07-15T00:00:00", "steps": 1234}
  ]
}
```

### 距離

#### `GET /api/children/{child_id}/distances?year=2026&month=7&day=15`

指定日の児童間距離を返します。`distances` は時刻順で、相手児童ID、相手児童名、距離、日時を含みます。`total_distance`、`avg_distance`、`meeting_count` と最大・最小距離も返します。データがない場合、距離配列は空で統計値は0です。

#### `GET /api/stats/distance-today?year=2026&month=7&day=15`

指定日の全距離データを集計します。全レコードの合計・平均・件数、児童別集計（合計距離、平均距離、件数）、距離が大きい上位5ペアを返します。ペアごとの集計は同一ペアの最後のレコードで上書きされます。

### 全体集計

#### `GET /api/stats/today?year=2026&month=7&day=15`

指定日の全児童の集計を返します。主な項目は次のとおりです。

- `total_steps`: 各児童のその日の最新歩数の合計
- `avg_steps`: 登録児童数で割った整数平均
- `goal_met_count`: 10,000歩以上の児童数
- `student_ranking`: 歩数の降順。歩数データがない児童も0歩で含む
- `steps_by_hour`: 0時から23時までの時間別歩数
- `warnings`: 過去7日間の平均の50%未満で、過去データが3件以上ある児童
- `walk_time`、`calories`、`step_change`、`step_change_percent`: 全体の歩数から計算した値

#### `GET /api/stats/monthly?year=2026&month=7`

指定月の全歩数レコードの合計、全距離レコードの合計、月末日、残日数を返します。対象月が現在月でない場合、`remaining_days` は0です。

## curlでの確認例

```sh
# ヘルスチェック
curl http://localhost:8000/api/health

# デバッグ児童を作成して一覧を見る
curl -X POST http://localhost:8000/api/create_debug_child
curl http://localhost:8000/api/children

# 歩数を送信
curl -X POST http://localhost:8000/api/push_data \
  -H "Content-Type: application/json" \
  -d '{"child_id":1,"singledata":{"steps":1234}}'

# 指定日の歩数を取得
curl "http://localhost:8000/api/children/1/steps?year=2026&month=7&day=15"
```

## ダミーデータ送信

20デバイスをシミュレートし、歩数と距離を継続的に送信します。サーバを起動した別のターミナルで実行してください。

```sh
uv run python dummy_data_sender.py
```

デバイスごとに4-15秒の送信間隔があり、歩数デバイスは累積歩数、距離デバイスは複数児童との2-60mの距離を送ります。児童数が足りない場合は `POST /api/create_debug_child` で自動作成し、`GET /api/children` の結果をデバイスに割り当てます。

## 児童データ管理（デバッグ用）

```sh
# 一覧表示
uv run python delete_children.py list

# すべての児童と関連データを削除
uv run python delete_children.py delete_all

# 指定した児童と関連データを削除
uv run python delete_children.py delete <child_id>
```

## データモデル

- `child`: `child_id`、名前、`device_id`
- `child_data`: 児童ごとの日時別歩数。受信した値は累積歩数として扱う
- `child_distance`: 児童ペア、距離、日時。児童IDは小さい順で保存する

## プロジェクト構造

```
sukusute_server/
├── sukusute_server/
│   ├── __init__.py        # FastAPIアプリとAPIルート
│   ├── __main__.py        # Uvicorn起動
│   ├── database_models.py # SQLAlchemyモデルとDB接続
│   └── http_models.py     # リクエスト・レスポンスモデル
├── frontend/              # ダッシュボード画面
├── migration/             # Alembicマイグレーション
├── dummy_data_sender.py   # 20デバイスシミュレータ
└── delete_children.py     # デバッグ用データ削除
```

## 現在のプロトタイプ上の注意

- 認証・認可はありません。CORSも開発用に全オリジン許可です。
- `device_id` は児童情報に保持しますが、`/api/push_data` では送信元デバイスとの照合をしていません。
- `GET /api/children/{child_id}/steps/history` は、存在しない `child_id` に対する明示的な404処理がまだありません。
- `steps_by_hour` は児童別歩数APIでは未実装で、空配列を返します。