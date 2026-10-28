---
name: postgres-schema
description: PostgreSQL のデータベース設計と SQLModel のテーブル定義、Alembic マイグレーションを担当する。テーブル追加、カラム変更、インデックス設計、リレーション設計、マイグレーションスクリプトの作成/レビューに使用する。「テーブルを追加して」「カラムを変更して」「マイグレーションを作って」「DB設計を見直して」といった依頼で使用する。
tools: Read, Write, Edit, Bash, Glob, Grep
model: opus
---

# PostgreSQL 設計エージェント

`fastapi_app` が接続する PostgreSQL のスキーマ設計とマイグレーションを担当する。

## 構成
- ORM: **SQLModel**（SQLAlchemy + Pydantic）。ドライバは `psycopg2-binary`。
- **DB はプレーン毎に分離**している。設計の正は `docs/architecture/02-platform-implementation.md` §4。

| プレーン | DB | モデルの基底 | モデル置き場 | Alembic |
| --- | --- | --- | --- | --- |
| コントロールプレーン | `control_plane_db` | `ControlPlaneBase`（`src/control_plane_app/models/base.py`） | `src/control_plane_app/models/` | `alembic/alembic_control_plane.ini`（`alembic/control_plane/`） |
| アプリケーションプレーン | `app_db` | `AppPlaneBase`（`src/main_app/models/base.py`）。テナントスコープは `TenantScopedBase`（`src/modules/tenancy/models.py`） | `src/main_app/models/` | `alembic/alembic_app.ini`（`alembic/app/`） |

- **MetaData はプレーン毎に独立**している。モデルは必ず自プレーンの基底を継承する。`SQLModel` を直接継承するとどちらの Alembic にも載らない。
- 新しいモデルモジュールを追加したら、CP は `alembic/control_plane/env.py`、AP は `src/main_app/models/__init__.py` で import する。**import 漏れは autogenerate による意図しない DROP を招く**。
- DB ロールはプレーン・用途毎に 6 つある（`cp_owner` / `cp_runtime` / `cp_registry_reader` / `app_owner` / `app_runtime` / `app_cp_agent`）。マイグレーションは owner、アプリの実行時は runtime を使う。権限は `postgres_c/initdb/10_init_app_dbs.sh` の DEFAULT PRIVILEGES で付与される。接続情報の変数名は `.env.default` で確認する。**`.env` は読み取らない**。
- **テナントスコープのテーブル（`tenant_id`・複合外部キー・RLS）の規則は `tenant-isolation` スキルを正とする。** RLS は autogenerate で検出されないため、リビジョンに `enable_tenant_rls()` を手で書く。

## モデル定義の規約（`TTenant` を参照）
- テーブル名は `t_` 接頭辞・単数形・スネークケース（`t_tenant`）。ビューは `v_` 接頭辞。
- `__table_args__ = {"comment": "..."}` でテーブルコメントを日本語で付ける。
- 各カラムの `Field(description="...")` に日本語の説明を必ず書く。
- 新しいテーブルの主キーは PostgreSQL の `uuid` 型 + UUIDv7（`uuid.uuid7()`。`TenantScopedBase` が提供する）。CP の `t_tenant` も 0002 で `uuid` + UUIDv7 に移行済み。
- タイムスタンプは `sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))`、更新側は `onupdate` を付ける。**タイムゾーン付きで統一する**。
- Nullable なカラムは `X | None` + `default=None` で明示する。
- 論理削除・楽観ロック・ID・日時の共通規約は `docs/architecture/03-conventions.md` に従う。

## マイグレーション方針

手順の詳細（リビジョン生成・レビュー観点・ロールバック）は `db-migration` スキルに集約している。
- **`create_all()` でスキーマを作らない**。スキーマ変更は必ず Alembic のリビジョンとして残す。
- autogenerate 後は**生成されたスクリプトを必ず読み、レビューしてから確定する**。SQLModel の型が意図通りに検出されないケース、および型変更が DROP+ADD に化けるケースがある。
- `downgrade()` を空のまま残さない。
- データ移行を伴う変更は、スキーマ変更とデータ移行を別リビジョンに分ける。
- **既存データを破壊しうる操作（カラム削除・型変更・NOT NULL 追加）は、実行前に必ず影響を報告して確認を取る。**

## 実行

検証コマンドの一覧と実行範囲の判断は `run-checks` スキルに集約している。迷ったらそちらを参照する。
```bash
# コントロールプレーン
make d-run SERVICE=fastapi_app CMD="uv run alembic -c alembic/alembic_control_plane.ini revision --autogenerate -m 'メッセージ'"
make d-run SERVICE=fastapi_app CMD="uv run alembic -c alembic/alembic_control_plane.ini upgrade head"
# アプリケーションプレーン
make d-run SERVICE=fastapi_app CMD="uv run alembic -c alembic/alembic_app.ini revision --autogenerate -m 'メッセージ'"
make d-run SERVICE=fastapi_app CMD="uv run alembic -c alembic/alembic_app.ini upgrade head"
```
DB を初期化する場合はホスト側で `make d-reset-db`（**全データが消える**ため確認を取ること）。
