---
name: db-migration
description: Alembic による PostgreSQL のマイグレーション手順。SQLModel のテーブル定義変更からリビジョン生成、生成物のレビュー、適用、ロールバックまでの一連の流れを扱う。「テーブルを追加した」「カラムを変更したのでマイグレーションを作りたい」「マイグレーションを適用して」「DBのスキーマを戻したい」といった依頼で使用する。
---

# Alembic マイグレーション手順

`fastapi_app` の PostgreSQL スキーマ変更は**必ず Alembic のリビジョンとして残す**。

## 前提

DB はプレーン毎に分かれており、Alembic の環境も 2 つある。**どちらの DB を変えるのかを最初に決め、`-c` で ini を明示する。**

| 項目 | コントロールプレーン（CP） | アプリケーションプレーン（AP） |
| --- | --- | --- |
| 設定ファイル | `alembic/alembic_control_plane.ini` | `alembic/alembic_app.ini` |
| マイグレーション環境 | `alembic/control_plane/env.py` | `alembic/app/env.py` |
| リビジョン置き場 | `alembic/control_plane/versions/` | `alembic/app/versions/` |
| モデル定義 | `src/control_plane_app/models/`（`ControlPlaneBase` を継承） | `src/main_app/models/`（`AppPlaneBase` / `TenantScopedBase` を継承） |
| `target_metadata` | `control_plane_metadata` | `app_plane_metadata` |
| 接続ロール | `CP_DB_OWNER_USER` / `CP_DB_OWNER_PASSWORD` + `CONTROL_PLANE_DB_NAME` | `APP_DB_OWNER_USER` / `APP_DB_OWNER_PASSWORD` + `APP_DB_NAME` |

- 共通: `DB_HOST` / `DB_PORT`。接続 URL は env.py で組み立てる（パスワードはログに出さない）。
- マイグレーションは**所有者ロール**で行う。実行時ロール（`*_runtime`）への権限は initdb の DEFAULT PRIVILEGES で自動付与されるため、リビジョンに GRANT は書かない（例外: `cp_registry_reader` へのビューの SELECT）。
- 以下では `<ini>` をどちらかの設定ファイルに読み替える。コンテナ内外の判定は `run-checks` スキルに従う（以下はコンテナ内での表記）。

---

## 手順

### 1. モデルを変更する

自プレーンの基底クラスを継承したテーブルモデルを編集する。命名・カラムコメント・タイムスタンプの規約は `postgres-schema` エージェントの定義に従う。テナントスコープのテーブルは `tenant-isolation` スキルにも従う。

### 2. モデルの import を確認する ← 最重要

MetaData はプレーン毎に独立しており、**import されたモデルだけ**が `target_metadata` に載る。

| プレーン | import する場所 |
| --- | --- |
| CP | `alembic/control_plane/env.py`（`from control_plane_app.models.sql_models import *`） |
| AP | `src/main_app/models/__init__.py` の `_TABLE_MODULES`（モジュール名）と `_EXPORTS`（公開するモデル名）。循環 import を避けるため遅延 import にしており、`app_plane_metadata` を参照した時点で `_TABLE_MODULES` を全部読み込む |

**新しいモデルモジュールを追加した場合は、上表の場所に追記する**（AP は import 文ではなく `_TABLE_MODULES` / `_EXPORTS` への追記）。

これを忘れると `target_metadata` にテーブルが載らず、autogenerate は「このテーブルはモデル側に存在しない」と解釈して **`DROP TABLE` を含むリビジョンを生成する**。気づかず適用するとデータが消える。**リビジョン生成前に必ず確認すること。**

また、`SQLModel` を直接継承したモデルはどちらの MetaData にも載らない。基底クラスを確認する。

### 3. リビジョンを生成する

```bash
uv run alembic -c <ini> revision --autogenerate -m "変更内容の要約"
```

### 4. 生成されたスクリプトをレビューする ← 必須

生成されたリビジョンファイルを**必ず開いて読む**。autogenerate は万能ではない。以下を確認する。

- **意図しない `DROP TABLE` / `DROP COLUMN` が含まれていないか**（手順2の漏れが原因のことが多い）
- カラムの型変更が `DROP COLUMN` + `ADD COLUMN` に化けていないか（**既存データが消える**）。その場合は `alter_column` に書き換える
- SQLModel 固有の型（`str | None` など）が期待通りの SQL 型として検出されているか
- `server_default` / `onupdate` の差分が毎回出ていないか（出るなら比較対象の設定を見直す）
- **`downgrade()` が空になっていないか。** 空のまま残さず、戻せる内容を書く
- **（AP）テナントスコープのテーブルを追加したなら、RLS を手で追加したか。** autogenerate は RLS を検出しない。`upgrade()` に `enable_tenant_rls("<table>")`、`downgrade()` に `disable_tenant_rls("<table>")`（`from modules.tenancy.rls import ...`）。テーブル作成の後に呼ぶ
- **（AP）複合外部キー・`UNIQUE (tenant_id, id)` が生成されているか**
- **他プレーンのテーブルが混ざっていないか**（基底クラスの継承誤り）

### 5. 適用する

```bash
uv run alembic -c <ini> upgrade head
```

### 6. 適用結果を確認する

```bash
uv run alembic -c <ini> current
uv run alembic -c <ini> history
```

---

## ロールバック

```bash
# 1つ前に戻す
uv run alembic -c <ini> downgrade -1
# 特定のリビジョンまで戻す
uv run alembic -c <ini> downgrade <revision_id>
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

- **`create_all()` でスキーマを作らない。** 変更履歴が残らず、所有者・権限も意図と異なる。スキーマ変更は必ずリビジョン化する。
- 適用済みのリビジョンファイルを後から書き換えない。修正は新しいリビジョンで行う。
- **`make d-reset-db` を安易に使わない。** PostgreSQL のボリュームを削除して作り直すため、**全データが失われる**。使うのは開発環境を初期状態に戻したいときだけで、実行前に必ず確認を取る。

---

## 困ったとき

| 症状 | 確認すること |
| --- | --- |
| autogenerate が空のリビジョンを吐く | モデルが `env.py` から読めているか、既に適用済みでないか |
| 意図しない DROP が出る | 手順2（`env.py` のインポート漏れ）を確認 |
| 接続エラーになる | `postgres_c` が起動しているか（`make d-ps`）、環境変数が入っているか |
| `role "cp_owner" does not exist` 等 | `postgres_c` が旧構成の initdb で作られている。ロール分離後の initdb は DB 初期化時にしか走らないため、`make d-reset-db` が必要（全データが消える。確認を取る） |
| `permission denied` | 実行時ロールでマイグレーションしていないか。所有者ロールの変数を確認 |
| `Target database is not up to date` | `upgrade head` を先に実行する |
