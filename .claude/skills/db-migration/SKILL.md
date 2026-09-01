---
name: db-migration
description: Alembic による PostgreSQL のマイグレーション手順。SQLModel のテーブル定義変更からリビジョン生成、生成物のレビュー、適用、ロールバックまでの一連の流れを扱う。「テーブルを追加した」「カラムを変更したのでマイグレーションを作りたい」「マイグレーションを適用して」「DBのスキーマを戻したい」といった依頼で使用する。
---

# Alembic マイグレーション手順

`fastapi_app` の PostgreSQL スキーマ変更は**必ず Alembic のリビジョンとして残す**。

## 前提

| 項目 | 値 |
| --- | --- |
| 設定ファイル | `alembic/alembic_control_plane.ini` |
| マイグレーション環境 | `alembic/control_plane/env.py` |
| リビジョン置き場 | `alembic/control_plane/versions/` |
| モデル定義 | `src/control_plane_app/models/sql_models.py` |
| 接続先 | 環境変数 `APP_DB_USER` / `APP_DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `CONTROL_PLANE_DB_NAME` |

コマンドはすべて `-c` で ini を明示する。コンテナ内外の判定は `run-checks` スキルに従う（以下はコンテナ内での表記）。

---

## 手順

### 1. モデルを変更する

`sql_models.py` のテーブルモデルを編集する。命名・カラムコメント・タイムスタンプの規約は `postgres-schema` エージェントの定義に従う。

### 2. `env.py` のインポートを確認する ← 最重要

`env.py` は以下でモデルを読み込み、`target_metadata` を組み立てている。

```python
from control_plane_app.models.sql_models import *  # noqa: F403
target_metadata = SQLModel.metadata
```

**新しいモデルモジュールを追加した場合は、`env.py` にそのインポートを追記する。**

これを忘れると `target_metadata` にテーブルが載らず、autogenerate は「このテーブルはモデル側に存在しない」と解釈して **`DROP TABLE` を含むリビジョンを生成する**。気づかず適用するとデータが消える。**リビジョン生成前に必ず確認すること。**

### 3. リビジョンを生成する

```bash
uv run alembic -c alembic/alembic_control_plane.ini revision --autogenerate -m "変更内容の要約"
```

### 4. 生成されたスクリプトをレビューする ← 必須

`alembic/control_plane/versions/` に生成されたファイルを**必ず開いて読む**。autogenerate は万能ではない。以下を確認する。

- **意図しない `DROP TABLE` / `DROP COLUMN` が含まれていないか**（手順2の漏れが原因のことが多い）
- カラムの型変更が `DROP COLUMN` + `ADD COLUMN` に化けていないか（**既存データが消える**）。その場合は `alter_column` に書き換える
- SQLModel 固有の型（`str | None` など）が期待通りの SQL 型として検出されているか
- `server_default` / `onupdate` の差分が毎回出ていないか（出るなら比較対象の設定を見直す）
- **`downgrade()` が空になっていないか。** 空のまま残さず、戻せる内容を書く

### 5. 適用する

```bash
uv run alembic -c alembic/alembic_control_plane.ini upgrade head
```

### 6. 適用結果を確認する

```bash
uv run alembic -c alembic/alembic_control_plane.ini current
uv run alembic -c alembic/alembic_control_plane.ini history
```

---

## ロールバック

```bash
# 1つ前に戻す
uv run alembic -c alembic/alembic_control_plane.ini downgrade -1
# 特定のリビジョンまで戻す
uv run alembic -c alembic/alembic_control_plane.ini downgrade <revision_id>
```

---

## 破壊的変更の扱い

以下は**既存データを失う可能性がある**。実行前に必ず影響を説明し、承認を得る。

- カラムの削除、テーブルの削除
- カラムの型変更（特に縮小方向、例: `str` → `int`）
- 既存行があるテーブルへの `NOT NULL` カラム追加（デフォルト値なしでは失敗する）
- カラムのリネーム（autogenerate は DROP + ADD として検出する。手書きで `alter_column` の `new_column_name` を使う）

データ移行を伴う場合は、**スキーマ変更のリビジョンとデータ移行のリビジョンを分ける**。

---

## やってはいけないこと

- **`SQLModel.metadata.create_all()`（`DBConnector.create_db_and_tables()`）でスキーマ変更を済ませない。** 現状 `src/control_plane_app/api_tenant/router.py` の lifespan がこれを呼んでいるが、これは初期化用であり、変更履歴は残らない。スキーマ変更は必ずリビジョン化する。
- 適用済みのリビジョンファイルを後から書き換えない。修正は新しいリビジョンで行う。
- **`make d-reset-db` を安易に使わない。** PostgreSQL のボリュームを削除して作り直すため、**全データが失われる**。使うのは開発環境を初期状態に戻したいときだけで、実行前に必ず確認を取る。

---

## 困ったとき

| 症状 | 確認すること |
| --- | --- |
| autogenerate が空のリビジョンを吐く | モデルが `env.py` から読めているか、既に適用済みでないか |
| 意図しない DROP が出る | 手順2（`env.py` のインポート漏れ）を確認 |
| 接続エラーになる | `postgres_c` が起動しているか（`make d-ps`）、環境変数が入っているか |
| `Target database is not up to date` | `upgrade head` を先に実行する |
