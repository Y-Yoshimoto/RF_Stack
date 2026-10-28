# 02. 共通基盤の実装方針（技術依存）

> ステータス: ドラフト v0.5
>
> [01-platform-concepts.md](01-platform-concepts.md) の概念・要件を、本リポジトリの技術スタックでどう実現するかを定める。
> 技術スタックを変更する場合は本書を差し替える。

---

## 1. 技術スタック

| 役割 | 採用技術 | 01 での呼び方 |
| --- | --- | --- |
| フロントエンド | React + MUI + React Router（Vite） | フロントエンド（SPA） |
| API サーバー / BFF | FastAPI（Python 3.14、SQLModel、httpx） | API サーバー |
| データベース | PostgreSQL 18 | CP DB / AP DB |
| IdP | Keycloak | IdP。認証領域 = レルム |
| セッションストア | Redis | セッションストア |
| 定期実行 | APScheduler（FastAPI プロセス内） | スケジューラ |
| マイグレーション | Alembic | — |
| リバースプロキシ | 開発: Vite dev server の proxy、本番: nginx（`rproxy`） | — |

---

## 2. コンテナ構成（開発環境）

`docker-compose.yaml` のサービス名がそのまま `docker compose exec` / `make d-run SERVICE=` の値になる。

| サービス | 技術 | 役割 | ポート |
| --- | --- | --- | --- |
| `react_app` | React / Vite | AP / CP 共通の単一ビルド SPA。`/api` を `fastapi_app` に proxy | 5173（dev）, 4173（preview）, 6006（Storybook） |
| `fastapi_app` | FastAPI | BFF・`/api/auth/*`・`/api/v1/*`・`/api/v1/cp/*`・`/api/v1/public/*`、組み込みスケジューラ | 8000 |
| `postgres_c` | PostgreSQL | `control_plane_db` と `app_db`（DB を分離） | 5432 |
| `keycloak_c` | Keycloak | `master` / `control-plane` / `tenant-{tenant_code}` レルム。開発ではファイル永続化（`db_data/keycloak`） | 8080 |
| `redis_c` | Redis | BFF のセッション、認可リクエストの一時状態 | 6379 |

- ブラウザからは SPA と API を**同一オリジン**（`http://localhost:5173`）で利用する
- Keycloak は別オリジン（`http://localhost:8080/keycloak`）。`KC_HOSTNAME` で issuer を外部 URL に固定し、FastAPI からは内部 URL（`http://keycloak_c:8080/keycloak`）でバックチャネル通信する
- 本番構成（`docker-compose-prod.yaml`）は `rproxy`（nginx）が `/api/` を FastAPI に転送する

---

## 3. Keycloak

### 3.1 レルムとクライアント

| レルム | クライアント | 種別 | 用途 |
| --- | --- | --- | --- |
| `master` | `cp-provisioner` | confidential、サービスアカウントのみ | レルムの作成・無効化・削除。`create-realm` ロールを付与（作成したレルムの管理権限は Keycloak が作成者に自動付与する） |
| `control-plane` | `fastapi-cp` | confidential、Standard Flow + PKCE(S256) | CP の BFF ログイン |
| `tenant-{tenant_code}` | `fastapi-app` | confidential、Standard Flow + PKCE(S256) | AP の BFF ログイン（`KEYCLOAK_CLIENT_ID` の既定値） |
| `tenant-{tenant_code}` | `tenant-user-admin` | confidential、サービスアカウントのみ | AP からのユーザー作成・無効化。`realm-management` の `manage-users` / `view-users` / `query-users` のみ |

- リダイレクト URI は全レルム共通で `{FRONTEND_URL}/api/auth/callback`（`state` に plane・レルムを紐づけて Redis に保存する）
- ログアウト後のリダイレクト: AP は `{FRONTEND_URL}/{tenant_code}/*`、CP は `{FRONTEND_URL}/cp/*`
- `directAccessGrantsEnabled` は **`APP_ENV=development` のときだけ** `true`（開発用ログインで使用）

### 3.2 テナントレルムのテンプレート

| 項目 | 設定 |
| --- | --- |
| レルム名 | `tenant-{tenant_code}` |
| メール | `duplicateEmailsAllowed=false`（レルム内 = テナント内で一意）、`loginWithEmailAllowed=true` |
| 登録・リセット | `registrationAllowed=false`、`resetPasswordAllowed=false`（メールサーバーが無いため） |
| ブルートフォース保護 | `bruteForceProtected=true` |
| レルムロール | `tenant_admin`, `member`（既定ロールに `member` を含める） |
| マッパー（`fastapi-app`） | ハードコードクレーム `tenant_id`（アクセストークン・ID トークン）、Audience マッパー（`aud` に `fastapi-app`） |
| 初期管理者 | 一時パスワード（`temporary=true`）+ 必須アクション `UPDATE_PASSWORD` |
| ユーザープロフィール | Keycloak の既定ではメール・姓・名が必須。払い出し・ユーザー作成時は必ず埋める（未入力だとログインが `Account is not fully set up` で失敗する） |

### 3.3 クライアントシークレットの導出

```
secret = base64url_nopad( HMAC-SHA256( KC_CLIENT_SECRET_SEED, "{realm}:{client_id}" ) )
```

- `KC_CLIENT_SECRET_SEED` は環境変数で与える（開発用の既定値は本番で拒否する）
- CP は払い出し時にこの値をクライアントに設定し、AP / CP の BFF は同じ式で導出して使う。DB には保存しない
- ローテーションはシード値を変更し、全レルムに「シークレット同期」ステップを再実行する

### 3.4 Admin API クライアント

- 共通部品 `fastapi_app/src/modules/keycloak_admin/`（httpx、FastAPI 非依存）に、冪等な `ensure_*` 関数として実装する
- 払い出し（CP）・ユーザー管理（AP）・開発用シード・CLI のいずれもこの部品を使う。トークン取得方法（`admin-cli` のパスワードグラント / `cp-provisioner` / `tenant-user-admin` のクライアントクレデンシャル）は差し替え可能にする
- 個々の HTTP 呼び出しにタイムアウトを設定する
- 開発時の単発セットアップは CLI（`python -m modules.keycloak_admin.cli`）で行う。手順は `tenant-provisioning` スキルを参照
- AP のユーザー管理は `templates.create_tenant_user_admin_client(realm_name)`（`tenant-user-admin` のクライアントクレデンシャル。トークンはテナントレルムで取得、シークレットは導出）と `tenant_users.py` の関数を使う。`tenant-user-admin` は `GET /roles/{name}` を呼べない（`view-realm` が無い）ため、`ensure_user_realm_roles` など払い出し用の関数は使わない

---

## 4. PostgreSQL

### 4.1 データベースとロール

| ロール | DB | 環境変数 | 権限 |
| --- | --- | --- | --- |
| `cp_owner` | `control_plane_db` | `CP_DB_OWNER_USER` / `CP_DB_OWNER_PASSWORD` | 所有者。Alembic（control_plane）専用 |
| `cp_runtime` | `control_plane_db` | `CP_DB_RUNTIME_USER` / `CP_DB_RUNTIME_PASSWORD` | テーブル DML、シーケンス |
| `cp_registry_reader` | `control_plane_db` | `CP_DB_REGISTRY_READER_USER` / `CP_DB_REGISTRY_READER_PASSWORD` | `v_tenant_registry` の SELECT のみ（ビュー作成時のマイグレーションで付与） |
| `app_owner` | `app_db` | `APP_DB_OWNER_USER` / `APP_DB_OWNER_PASSWORD` | 所有者。Alembic（app）専用 |
| `app_runtime` | `app_db` | `APP_DB_RUNTIME_USER` / `APP_DB_RUNTIME_PASSWORD` | テーブル DML。RLS 適用 |
| `app_cp_agent` | `app_db` | `APP_DB_CP_AGENT_USER` / `APP_DB_CP_AGENT_PASSWORD` | SELECT / DELETE のみ。RLS 適用 |

- ロールと DB は `postgres_c/initdb/` で作成する。全ロール `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`
- 実行時ロールへの権限は `ALTER DEFAULT PRIVILEGES FOR ROLE <owner>` で付与し、マイグレーションのたびに GRANT を書かなくてよいようにする
- `REVOKE ALL ON DATABASE ... FROM PUBLIC` とし、各ロールは自分の DB にのみ接続できる。`postgres` / `template1` / `runtime_db` からも PUBLIC の `CONNECT` / `TEMPORARY` を外している（`runtime_db` はスーパーユーザーの動作確認用）
- `public` スキーマの所有者を各 DB の owner にし、CREATE は owner のみに許可する
- パスワードは `psql -v` で渡し、シェル展開・ログ出力をしない。initdb は**データ初期化時にしか実行されない**ため、ロール構成を変えたら `make d-reset-db` が必要（全データが消える）
- 本番では実行時ロールの資格情報だけを API サーバーに渡し、所有者ロールはマイグレーションジョブにだけ渡す

### 4.2 RLS

```sql
ALTER TABLE t_xxx ENABLE ROW LEVEL SECURITY;
ALTER TABLE t_xxx FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON t_xxx
  USING      (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid);
```

- `NULLIF(..., '')` は、同一セッションで一度設定した GUC がトランザクション終了後に空文字に戻るため必要（空文字の `::uuid` はエラーになる）
- テナントコンテキストは `SELECT set_config('app.current_tenant', :tenant_id, true)`（= `SET LOCAL`）でトランザクション単位に設定する。コネクションプールに値は残らない
- SQLAlchemy の Session の `after_begin` イベントで、`contextvars` のテナントコンテキストから自動設定する（`modules/tenancy/db.py`）
- マイグレーションでは `modules/tenancy/rls.py` のヘルパー（`enable_tenant_rls` / `disable_tenant_rls`）を使う。RLS ポリシーは Alembic の autogenerate で検出されないため、**テナントスコープのテーブルを追加するリビジョンには必ず手で書く**（`db-migration` スキル参照）

### 4.3 テーブル設計の実装規則

- テーブル名は `t_` 接頭辞・単数形・スネークケース（例: `t_tenant`, `t_user`）。ビューは `v_` 接頭辞
- 主キーは PostgreSQL の `uuid` 型、値は UUIDv7（Python の `uuid.uuid7()`）。詳細は [03](03-conventions.md)
- テナントスコープのテーブルは `modules/tenancy/models.py` のベースを継承し、`tenant_id`（`uuid`、NOT NULL、インデックス）を持つ
- 外部キーは `(tenant_id, id)` の複合キーで参照する。参照される側に `UNIQUE (tenant_id, id)` を置く

```sql
ALTER TABLE t_todo ADD CONSTRAINT uq_todo_tenant_id UNIQUE (tenant_id, id);
ALTER TABLE t_todo_assignee
  ADD CONSTRAINT fk_todo_assignee_todo
  FOREIGN KEY (tenant_id, todo_id) REFERENCES t_todo (tenant_id, id);
```

### 4.4 マイグレーション

| プレーン | 設定 | 環境 | 接続ロール |
| --- | --- | --- | --- |
| CP | `fastapi_app/alembic/alembic_control_plane.ini` | `alembic/control_plane/` | `cp_owner` |
| AP | `fastapi_app/alembic/alembic_app.ini` | `alembic/app/` | `app_owner` |

- SQLModel の `MetaData` を**プレーン毎に分ける**。各 `env.py` は自プレーンの `MetaData` だけを `target_metadata` にする（他プレーンのテーブルを作る・消すリビジョンが生成されるのを防ぐ）
- `SQLModel.metadata.create_all()` は使わない。スキーマ変更はすべてリビジョンとして残す
- プレーン毎の基底: CP は `ControlPlaneBase`（`control_plane_app/models/base.py`）、AP は `AppPlaneBase`（`main_app/models/base.py`）。AP のモデルは `main_app/models/__init__.py` で import して MetaData に載せる
- CP の初期リビジョンは `0001_create_t_tenant`（既存の `t_tenant` をそのまま作成）。`0002_revise_cp_tables` で 01 の 9.5 に沿って改訂した（4.6）
- AP のリビジョンは `0001_create_ap_common_tables`（01 の 9.4 の共通テーブル）、`0002_create_todo_tables`（ToDo のテーブル。[ToDoApp.md](../spec/ToDoApp.md) §9.1）。テーマのテーブルは基盤の共通テーブルとリビジョンを分ける（4.7）
- ビュー・GRANT / REVOKE は autogenerate で検出されないため、リビジョンに手で書く。ロール名はハードコードせず、マイグレーション実行時の環境変数（`CP_DB_REGISTRY_READER_USER` 等）から取ってクォートする

### 4.5 プレーン間アクセスの実装

| 01 の依存 | 接続 | 実装 |
| --- | --- | --- |
| AP → CP（レジストリ参照） | `cp_registry_reader` で `control_plane_db` の `v_tenant_registry` | `modules/tenancy/registry.py` の `TenantRegistry`。プロセス内 TTL キャッシュ（30 秒） |
| CP → AP（集計・物理削除） | `app_cp_agent` で `app_db` | テナント毎に `set_config` でコンテキストを切り替える。CP のリポジトリ層に閉じ込める |

### 4.6 CP のテーブル

01 の 9.5 の実装。モデルは `control_plane_app/models/sql_models.py`、スキーマはリビジョン `0002_revise_cp_tables`。

| 01 の名称 | テーブル / ビュー | 主キー | 実装上の注記 |
| --- | --- | --- | --- |
| テナント | `t_tenant` | `id`（UUIDv7） | `tenant_code` / `realm_name` は通常の UNIQUE（部分インデックスにしない。DELETED 後も再利用させないため）。`status` と `tenant_code` の形式（01 の 5.1）を CHECK で強制。予約語の拒否はアプリ層。楽観ロックの `version` と `created_by` / `updated_by`（CP 管理者の IdP subject または `system`）を持つ |
| 払い出し履歴 | `t_provisioning_history` | `id`（UUIDv7） | `type` は `onboard` / `offboard`、`status` は `RUNNING` / `SUCCEEDED` / `FAILED` / `SKIPPED`（CHECK）。`tenant_id` は `t_tenant` への外部キー |
| 日次メトリクス | `t_tenant_daily_metric` | `(tenant_id, date, metric_key)` | `value` は `numeric`（浮動小数点を使わない）。日次スナップショットの再実行は `ON CONFLICT ... DO UPDATE` で上書きする |
| 定期ジョブ実行履歴 | `t_scheduled_job_run` | `id`（UUIDv7） | `status` は払い出し履歴と同じ値。advisory lock を取れずにスキップした実行は `SKIPPED` で記録できる |
| CP 監査ログ | `t_cp_audit_log` | `id`（UUIDv7） | 03 の 7 章の `target_type` / `target_id` も持つ。`cp_runtime` から UPDATE / DELETE を REVOKE し追記のみとする。`target_tenant_id` に外部キーは張らない。`updated_at` は持たない |
| テナントレジストリ公開ビュー | `v_tenant_registry` | — | `t_tenant` の `id AS tenant_id, tenant_code, realm_name, status`（`public` スキーマ、`status <> 'DELETED'`）。SELECT は `cp_registry_reader` にのみ付与 |

- `v_tenant_registry` は `security_invoker` を付けない通常のビューとし、所有者（`cp_owner`）の権限で `t_tenant` を読む。`cp_registry_reader` は `t_tenant` を直接読めない
- DEFAULT PRIVILEGES により `cp_runtime` もビューの DML 権限を持つが、`t_tenant` の DML 権限を既に持つため権限の拡大にはならない
- 状態の値は `control_plane_app.models.sql_models.TenantStatus` を正とし、AP 側の `modules.tenancy.registry.TenantStatus` と一致させる
- `updated_at` は SQLAlchemy の `onupdate`（アプリ側）で更新する。`version` の +1 は更新処理側で行う

### 4.7 AP のテーブル

01 の 9.4 の実装。モデルは `main_app/models/ap_common.py`、スキーマはリビジョン `0001_create_ap_common_tables`。テーマ（ToDo）のテーブルは [ToDoApp.md](../spec/ToDoApp.md) §9.1。

| 01 の名称 | テーブル | 主キー | 実装上の注記 |
| --- | --- | --- | --- |
| ユーザー | `t_user` | `id`（UUIDv7） | 一意は `UNIQUE (tenant_id, idp_subject)` と一意インデックス `(tenant_id, lower(email))`。`idp_subject` はテナントレルムの `sub`。`email` は IdP 側で未設定の場合に備えて NULL 可（NULL 同士は一意制約に掛からない）。論理削除せず `is_active` で無効化する。楽観ロックの `version`。`created_by` / `updated_by` はログイン時の自動作成・同期などシステム処理では NULL |
| 組織 | `t_organization` | `id`（UUIDv7） | 論理削除。組織名は有効な組織の中でテナント内一意（`(tenant_id, lower(name)) WHERE deleted_at IS NULL` の部分一意インデックス）。楽観ロックの `version` |
| 組織メンバー | `t_organization_member` | `(tenant_id, organization_id, user_id)` | 行の追加・削除のみ（更新しない）。組織を論理削除しても行は残す。逆引き用に `(tenant_id, user_id)` |
| AP 監査ログ | `t_ap_audit_log` | `id`（UUIDv7） | 03 の 7 章の列（操作者は `actor_id`、システム処理は NULL）。`app_runtime` から UPDATE / DELETE を REVOKE し追記のみとする（`app_cp_agent` の SELECT / DELETE は既定権限のまま）。`actor_id` / `target_id` に外部キーは張らない。`updated_at` は持たない |

- すべてのテーブルが `tenant_id`（NOT NULL）・RLS（ENABLE / FORCE + `tenant_isolation`）を持ち、検索用のインデックスは `tenant_id` を先頭にする
- 参照される側は `UNIQUE (tenant_id, id)`、外部キーは `(tenant_id, <列>) → (tenant_id, id)`。`ON DELETE` は指定しない（物理削除はテナント物理削除でのみ行い、`control_plane_app/repositories/app_tenant_data.py` の `TENANT_DATA_PURGE_TABLES` に子テーブルから順に並べる）
- 中間テーブル（主キーが複合のもの）は `TenantScopedMixin` + `AppPlaneBase` で定義し、`PrimaryKeyConstraint` を `__table_args__` に置く
- 列の部品（`created_at` / `updated_at` / `deleted_at` / `version`、列挙値の CHECK）は `main_app/models/columns.py`
- 制約名は `modules/db_connector/metadata.py` の命名規約に従う（例: `t_todo_status_check`、`t_todo_tenant_id_created_by_fkey`）。関数・部分インデックスは `<table>_<内容>_key`（一意）/ `ix_<table>_<列>` の名前を明示する
- 払い出し時の AP の初期データ（01 の 6.2 ステップ 5・6: 初期管理者のユーザー行・デフォルト組織）は CP からは作らない（`app_cp_agent` は SELECT / DELETE のみのまま）。AP がログイン完了時に `app_runtime` で作る（`main_app/services/user_sync.py` の `sync_user_on_login`。5.1、05 #31）。デフォルト組織は `t_organization` に行が 1 件も無い（論理削除済みを含む）ときに作り、名前は `デフォルト組織`

---

## 5. FastAPI

### 5.1 ディレクトリ構成

```
fastapi_app/
  src/
    app.py                    # ルーターのマウント、lifespan、例外ハンドラ登録のみ
    modules/                  # 共通部品（プレーン非依存）
      auth/                   # BFF: セッション、トークン検証、認証依存関数
      db_connector/           # エンジン・セッション生成
      tenancy/                # テナントコンテキスト、RLS、テナントレジストリ、テナントスコープのモデル基底
      keycloak_admin/         # Keycloak Admin API クライアント（冪等 ensure 関数、CLI）
      tenant_metrics/         # 日次メトリクスの指標セットの定義と、テーマ固有指標の登録箇所（01 の 13 章 #5）
      api_common/             # API 規約の部品（UTC の日時型、カーソル方式のページネーション、ETag / If-Match）
      errors/                 # Problem Details の例外・ハンドラ・OpenAPI への反映、リクエスト ID
      logging/                # 構造化ログ（予定）
    control_plane_app/        # コントロールプレーン
      apiapp.py               # /api/v1/cp ルーター（認可: saas_admin / saas_viewer + CSRF）
      api_tenants/            # /api/v1/cp/tenants（fastapi-api-schema）
      api_metrics/            # /api/v1/cp/tenants/{id}/metrics、/api/v1/cp/metrics/summary
      problems.py             # 払い出しサービスの例外 → Problem Details
      services/               # 払い出し・メトリクス等（fastapi-domain）
      repositories/           # DB アクセス（AP DB への集計・物理削除もここに閉じ込める）。tenant_query.py は一覧・メトリクスの読み取り専用クエリ
      models/                 # CP の SQLModel（postgres-schema）
      jobs/                   # 定期ジョブ本体（APScheduler に依存しない関数）
    main_app/                 # アプリケーションプレーン
      route/                  # ルーター。auth（/api/auth）、public（/api/v1/public）、v1（/api/v1。AP）
      services/
      repositories/
      models/                 # AP の SQLModel
    scheduler/
      schedule.py             # ジョブと周期の定義
      runner.py               # APScheduler の起動・停止とジョブ登録、有効/無効の判定
  alembic/
    control_plane/            # CP DB のマイグレーション
    app/                      # AP DB のマイグレーション
```

- `main_app` は `control_plane_app` を import しない（逆も同様）。共有は `modules` のみ
- CP のテナント払い出し（実装済み）:

| モジュール | 内容 |
| --- | --- |
| `control_plane_app/services/tenant_provisioning.py` | `TenantProvisioningService`（`onboard` / `retry` / `suspend` / `resume` / `request_deletion` / `deprovision`）。FastAPI 非依存で、CP DB の `Session` と Keycloak の管理クライアントを受け取り、コミットはサービスが行う |
| `control_plane_app/services/errors.py` | 例外と Problem Details の `code`・HTTP ステータスの対応 |
| `control_plane_app/services/tenant_lifecycle.py` | 状態遷移（01 の 6.1）と操作ごとの遷移元。猶予期間 30 日、中断判定 10 分 |
| `control_plane_app/services/tenant_maintenance.py` | 中断した払い出しの回収（`reap_stale_provisioning`）、物理削除の対象の抽出 |
| `control_plane_app/repositories/` | CP DB の台帳・履歴・監査ログ、advisory lock、AP DB のテナントデータ削除（`app_tenant_data.py` の `TENANT_DATA_PURGE_TABLES` が 01 の 13 章 #9 の拡張点） |
| `control_plane_app/jobs/` | `provisioning_reaper` / `tenant_purge` / `metrics_snapshot` の本体（`python -m control_plane_app.jobs <job_name>` でも実行できる）。周期と起動は `scheduler/`（5.5） |
| `control_plane_app/seed.py` | 開発用シード（7.1） |

  使い方と守ることは `tenant-provisioning` スキルの 3 章を参照する
- AP のユーザー・組織管理とログイン時のユーザー同期（サービス・ログイン処理・`/api/v1` のルーターへの組み込みまで実装済み）:

| モジュール | 内容 |
| --- | --- |
| `main_app/services/user_sync.py` | `sync_user_on_login(session, *, tenant_id, idp_subject, email, display_name) -> UserSyncResult`（01 PF-USR-04 / 05。行の作成・表示名とメールの同期・`last_login_at`、デフォルト組織の作成。コミットする。無効なユーザーは `UserDeactivatedError`）、`require_active_session_user(session, *, idp_subject)`（PF-USR-03。各リクエストで呼ぶ） |
| `main_app/services/user_service.py` | `UserService(session, kc_admin_factory)`（`list_users` / `get_user` / `get_user_roles` / `create_user` / `update_user`）。作成は Keycloak → AP の順で、AP 側が失敗したら Keycloak のユーザーを削除する。一時パスワードは戻り値で一度だけ返す |
| `main_app/services/organization_service.py` | `OrganizationService(session)`（`list_organizations` / `get_organization` / `list_member_ids` / `create_organization` / `update_organization` / `delete_organization`（論理削除）/ `set_members`（全置換）） |
| `main_app/services/errors.py` | 例外と Problem Details の `code`・HTTP ステータスの対応（他テナント・存在しないリソースは同じ 404） |
| `main_app/services/common.py` | `UserView` / `OrganizationView`、PATCH の未指定を表す `UNSET`、監査ログ・操作者の解決 |
| `main_app/repositories/` | `users.py` / `organizations.py`（既定で論理削除済みを除く）/ `audit_log.py` / `keyset.py`（キーセット方式の一覧。カーソル文字列化は API 層） |
| `modules/keycloak_admin/tenant_users.py` | `tenant-user-admin` の権限で動く Keycloak 操作（作成は冪等にせず 409 を返す、ロールは `role-mappings/realm/available` から付与、無効化・セッション失効）。管理クライアントは `templates.create_tenant_user_admin_client(realm_name)` |

  - FastAPI 非依存。テナントコンテキスト下の AP セッション（`AppSessionDep` / `open_app_session()`）を受け取り、コミットはサービスが行う。テナントはコンテキストから得る（`sync_user_on_login` の `tenant_id` はコンテキストとの一致確認のみ）
  - 楽観ロック: `update_*` / `delete_*` / `set_members` は `expected_version`（`If-Match`）を取り、行ロックの下で確認して `version` を +1 する。変更が無い更新は何もしない（`version` も変えない）。ログイン時の同期は表示名・メールが変わったときだけ +1（`last_login_at` だけなら変えない）
  - 監査ログ（`t_ap_audit_log`）: `user.create`（`source` が `admin` / `login`）/ `user.sync` / `user.update` / `user.activate` / `user.deactivate` / `organization.create`（`source` が `admin` / `default`）/ `organization.update` / `organization.delete` / `organization.set_members`。操作者は `t_user.id`（セッションの `sub` から解決。ログイン時の同期・デフォルト組織は NULL）。一時パスワードは残さない
  - ロール: 付与できるのは `tenant_admin` / `member` のみ（`update_user(roles=...)` は直接付与の集合。`member` は既定ロールでも付与される）。ロールは AP の DB に持たず Keycloak が正。自分自身の無効化・`tenant_admin` の解除は 409
  - 表示名は Keycloak の姓・名から `"{名} {姓}"`（`name` クレームと同じ）で作る。ログイン時の同期で上書きされないよう、変更は Keycloak の姓・名に対して行う（`update_user(first_name=..., last_name=...)`）。ログイン処理は `display_name` に `name` クレーム（無ければ `preferred_username`）を渡す
  - **無効化したユーザーのセッション失効（01 PF-USR-03、05 #32）**: `update_user(is_active=False)` は Keycloak のユーザーを無効化し、Keycloak のセッションを失効させる（`POST /users/{id}/logout`。BFF のトークン更新が失敗し、遅くともアクセストークンの期限でセッションが破棄される）。即時の失効は AP 側で行う: `/api/v1` の各リクエストで `require_active_session_user` を呼び、`UserDeactivatedError` / `UserNotSyncedError` なら Redis のセッションを破棄して 401 を返す（`t_user.is_active` を正とし、キャッシュしない。一意制約 `(tenant_id, idp_subject)` による 1 回の SELECT）。`tenant_admin` を外した場合も Keycloak のセッションを失効させる（BFF のセッションのロールはログイン時の値のため）
  - ログイン処理への組み込み（実装済み。5.2 の「ログイン時のユーザー同期」）: コールバックと開発用ログインの AP の分岐が、セッションを作る前に `main_app/route/auth/login_sync.py` の `sync_app_user_on_login` 経由で `sync_user_on_login` を呼ぶ
  - `/api/v1` への組み込み（実装済み。5.6）: ルーター全体に依存関数 `require_active_app_user`（`require_active_session_user` を呼び、失効時は Redis のセッションを削除して 401）、`/api/v1/users`・`/api/v1/organizations` が各サービスを呼ぶ（`main_app/route/v1/`）
- 例外: AP のテナントレジストリ参照は `modules/tenancy/registry.py` の読み取り専用インターフェース経由
- 各層の担当エージェント: ルーター・スキーマ → `fastapi-api-schema`、サービス・共通部品 → `fastapi-domain`、モデル・マイグレーション → `postgres-schema`、テスト → `fastapi-pytest`、認証 → `auth-keycloak`

### 5.2 認証（BFF）

| 項目 | 実装 |
| --- | --- |
| セッション Cookie | AP: `rf_sid_app`、CP: `rf_sid_cp`。`HttpOnly`、`SameSite=Lax`、`Secure` は `APP_ENV` から導出。値は `itsdangerous` でプレーン毎の salt を使って署名 |
| セッションストア | Redis。キーは `session:app:{sid}` / `session:cp:{sid}`、TTL は `SESSION_TTL_SECONDS` |
| セッションの内容 | `plane`, `realm`, `tenant_id` / `tenant_code`（AP のみ）, `user`, `tokens`。`user` は `sub`, `preferred_username`, `name`, `email`, `realm`, `plane`, `roles`（プレーンの許可リストにあるレルムロールのみ）で、AP のみ `tenant_id` を加える。`name` はログイン時のユーザー同期に使い、`/api/auth/*/status` では返さない |
| 認可リクエストの一時状態 | Redis `auth_state:{state}`（TTL 300 秒）に `plane`, `realm`, `code_verifier`, `nonce` |
| トークン検証 | レルム毎の JWKS を `PyJWKClient` でキャッシュ。issuer は内部・外部 URL の両方を許可（`KC_HOSTNAME` 固定前提）。アクセストークンはアクセスのたびに期限を確認し、切れていればサーバー側で更新する |
| 認証依存関数 | `modules/auth/dependency.py` の `get_current_app_user` / `get_current_cp_user`（未認証・別プレーンのセッションは 401）、`require_app_roles` / `require_cp_roles`（ロール不足は 403）。AP ルーターはさらに `AppTenantContextDep`（`modules/tenancy/app_dependency.py`。レジストリ照合、停止中・不一致は 403）を適用する。Cookie は `APIKeyCookie`（`auto_error=False`）で読み、OpenAPI ではパラメータではなくセキュリティスキーム `AppSession` / `CpSession` になる |
| CSRF | ミドルウェアではなく**依存関数** `require_csrf_protection`（`modules/auth/csrf.py`）。変更系メソッド（POST / PUT / PATCH / DELETE）で `X-Requested-With: rf-stack` と、許可したオリジン（`FRONTEND_URL` と `CSRF_TRUSTED_ORIGINS`）に一致する `Origin` を検証し、不足は 403。参照系は素通りするため、ルーター単位で付ける（`/api/v1` と `/api/v1/cp` のルーター、ログアウトに適用済み）。`X-Requested-With` は `Header` 引数として宣言し、`install_csrf_openapi` が OpenAPI 上で変更系だけの必須ヘッダー（値は `rf-stack`）に直す |
| ログイン時のユーザー同期（AP のみ） | 01 PF-USR-04 / 05、05 #31。コールバックと開発用ログインの AP の分岐で、トークンの検証後・**セッションを作る前**に `main_app/route/auth/login_sync.py` の `sync_app_user_on_login` を呼ぶ。レジストリで確認したテナント（`tenant_id` / `tenant_code`）で `tenant_scope` を設定し、`open_app_session()`（`app_runtime`、RLS）で `sync_user_on_login` を呼ぶ（ユーザー行の作成・表示名とメールの同期・`last_login_at` の更新、デフォルト組織の作成。コミットは同期処理）。表示名は `name` クレーム、無ければ `preferred_username`。無効化されたユーザー（`UserDeactivatedError`）はセッションを作らず、コールバックは `login_rejected`、開発用ログインは 403（`login_rejected`）。AP の DB に接続できない場合はコールバックは `service_unavailable`、開発用ログインは共通の例外ハンドラで 503。それ以外の失敗は `internal_error` / 500。**CP のログインとトークン更新では呼ばない**（トークン更新で `last_login_at` を更新しない） |
| フロントエンドへの遷移先 | `modules/auth/redirects.py` に集約（下表）。ホスト部は常に `FRONTEND_URL`。テナントコードはサーバー側の値（レジストリ・state・セッション）だけを使い、形式に合わなければ `/` にする。開発用ログインの `next` はパスのみ許可 |

**遷移先**（01 の 11.1 のルーティングに合わせる）

| 場面 | AP | CP |
| --- | --- | --- |
| ログイン成功（コールバック） | `/{tenant_code}/` | `/cp/` |
| ログイン開始で利用できないテナント（形式不正・未登録・非 ACTIVE を区別しない） | `/?error=tenant_unavailable` | — |
| コールバックの失敗（JSON は返さない） | `/{tenant_code}/login?error=<code>`（state からテナントが分からなければ `/?error=<code>`） | `/cp/login?error=<code>` |
| ログアウト後（`POST .../logout` の応答 `logout_url` は Keycloak のログアウト URL で、完了後にここへ戻る） | `/{tenant_code}/login` | `/cp/login` |
| 開発用ログインの `next` 省略時 | `/{tenant_code}/` | `/cp/` |

コールバックの `error`（`modules.auth.redirects.LoginErrorCode`。Problem Details の `code` と同じ語彙。詳細はサーバーのログにだけ残す）:

| `error` | 失敗 |
| --- | --- |
| `invalid_auth_state` | state が無い・期限切れ・使用済み・内容が不正 |
| `authorization_failed` | 認可コードが無い（利用者のキャンセル、Keycloak のエラー） |
| `tenant_unavailable` | ログイン開始後にテナントが ACTIVE でなくなった、レルムとテナントコードが食い違う |
| `identity_provider_unreachable` | Keycloak に到達できない |
| `token_exchange_failed` | 認可コードをトークンに交換できない |
| `invalid_token` | トークンの欠落、署名・クレーム（`nonce` / `aud` / `azp` / `iss` / `exp`）の検証失敗 |
| `login_rejected` | `tenant_id` クレームの不一致、CP のロール不足、CP の state に control-plane 以外のレルム、AP で無効化されたユーザー（理由を区別しない） |
| `service_unavailable` | Redis・DB に接続できない |
| `internal_error` | 想定外のエラー |

### 5.3 テナントコンテキスト

| モジュール | 依存 | 役割 |
| --- | --- | --- |
| `modules/tenancy/context.py` | なし | `TenantContext` と `contextvars`、`tenant_scope()` |
| `modules/tenancy/registry.py` | SQLAlchemy（DB 実装のみ） | `TenantRegistry` Protocol、`CachedTenantRegistry`（TTL 30 秒）、`SqlTenantRegistry`（`v_tenant_registry`） |
| `modules/tenancy/resolver.py` | なし | セッションのユーザー情報 → `TenantContext`。クレーム欠落・未登録・レルム不一致・非 ACTIVE を判定 |
| `modules/tenancy/db.py` | SQLAlchemy | `app.current_tenant` の設定（`apply_tenant_guc`、`after_begin` リスナー、`tenant_guc_scope`、`run_per_tenant`） |
| `modules/tenancy/dependency.py` | FastAPI | リゾルバを受け取り、リクエスト中だけ contextvar を設定する async yield 依存関数を生成 |
| `modules/tenancy/models.py` | SQLModel | テナントスコープのテーブルの基底 |
| `modules/tenancy/rls.py` | Alembic | RLS ポリシーの作成・削除 |

- 依存関数は **async の yield 依存**にする。同期の yield 依存はスレッドプール内のコピーされた Context で動き、設定した contextvar がエンドポイントに伝わらないため
- `after_begin` リスナーは **`app_db` 用の Session にだけ**登録する（Session クラス全体に登録すると CP DB にも効く）
- ロガーは contextvar を参照して `tenant_id` 等をログに付与する

### 5.4 予約語

- 正は `modules/tenancy/tenant_code.py` の `RESERVED_TENANT_CODES`（バックエンド）とする。払い出しサービス（`onboard`）が形式とあわせて検証する（`validate_tenant_code`）
- フロントは `react_app/src/shared/tenant_code.ts` に同じ形式と予約語の写しを 1 箇所だけ持つ。予約語・形式違反の URL では API を呼ばずに「見つからない」を表示し、無駄なリクエストとレート制限の消費を避けるためである。最終的な判定は常にバックエンド（公開のテナント存在確認 API は予約語も 404）で行い、写しがずれても安全側に倒れる。予約語を変えるときは両方を更新する（バックエンド内の 4 箇所の一致は `test/auth/test_00_plane.py` で確認しているが、React 側の写しとの一致はまだテストしていない）
- 静的ルート（`/`、`/cp/*`、予約語）を `/:tenantCode/*` より先に定義する

### 5.5 定期実行

- `scheduler/runner.py` が FastAPI の lifespan で APScheduler（3 系の `BackgroundScheduler`。ジョブはスレッドで実行）を起動・停止する。スケジュール定義は `scheduler/schedule.py` の `SCHEDULED_JOBS` だけに置く
- 環境変数 `SCHEDULER_ENABLED`（`true` / `false`）で有効/無効を切り替える。**未設定なら `APP_ENV=development` で無効、それ以外で有効**（開発環境ではバックグラウンドで DB に書き込まない。本番で設定漏れによりジョブが止まらないようにする）。不正な値は起動時にエラー
- 複数ワーカー構成では 1 つ以外で無効化するか、advisory lock に任せる。別プロセスで動かす場合は `python -m scheduler`（`SCHEDULER_ENABLED` に関係なく起動する）を使い、API 側を `SCHEDULER_ENABLED=false` にする
- ジョブ実行時に `pg_try_advisory_lock(hashtext('<job_name>'))` を CP DB で取得し、取れなければ `SKIPPED` を記録してスキップする。同一プロセス内は `max_instances=1`、遅れた実行は `coalesce` で 1 回にまとめる
- ジョブ本体は `control_plane_app/jobs/` の普通の関数とし、CLI からも実行できる（`python -m control_plane_app.jobs <job_name>`）

| ジョブ | 周期（UTC） | 実装 |
| --- | --- | --- |
| `metrics_snapshot` | 毎日 23:45 | `control_plane_app/jobs/metrics_snapshot.py`。下記 |
| `tenant_purge` | 毎日 18:00（日本時間 03:00） | `control_plane_app/jobs/tenant_purge.py` |
| `provisioning_reaper` | 10 分毎 | `control_plane_app/jobs/provisioning_reaper.py` |

**`metrics_snapshot`**（01 の 6.4）

- 対象は `ACTIVE` と `SUSPENDED` のテナント（停止中もデータは残り、推移を途切れさせないため）。払い出し未完了・削除に向かう状態は対象外
- 集計対象日（`t_tenant_daily_metric.date`）は**実行時の UTC の当日**。値は「その日に取得した時点の状態」で、同じ日の再実行は `ON CONFLICT (tenant_id, date, metric_key) DO UPDATE` で上書きする（値が同じ行は更新しない）。前日にしないのは、過去の状態を求め直せないスナップショットを日中の手動実行で前日の行に書かないため。このため定期実行は UTC の 1 日の終わり近くに置き、23:55 までに開始できなければその日は実行しない
- 集計は `control_plane_app/repositories/app_tenant_metrics.py`（`app_cp_agent`、テナント毎に `tenant_guc_scope` で GUC を切り替え、`REPEATABLE READ` の読み取りトランザクション）、保存は `daily_metric_repository.py`。テナント毎にコミットし、1 テナントの失敗で他は止めない（ジョブは `FAILED`）
- 指標は「指標キーと集計関数」の組（`modules/tenant_metrics/definition.py` の `TenantMetricSet`。1 回のクエリで複数キーを返せる）。基盤の `users_total` / `users_active`（`t_user` の総数・`is_active` の数）は CP のリポジトリが持つ
- **テーマ固有指標の拡張点**（01 の 13 章 #5）: テーマは `main_app` 側に `TenantMetricSet` を定義し、`modules/tenant_metrics/registry.py` の `THEME_METRIC_SOURCES` に `"<モジュール>:<属性>"` を追加する。`control_plane_app` は `main_app` を import しないため、文字列で読み込む。キーが重複すると集計時にエラーになる。`primary_keys` はテナント一覧に出す主要指標の宣言（`theme_primary_metric_keys()`。`GET /api/v1/cp/tenants` の `primary_metrics` に直近の日次メトリクスの値を載せる。5.6）

### 5.6 API 層（ルーティング・エラー・規約）

実装は `app.py`（ルーターのマウント、lifespan、例外ハンドラ、リクエスト ID のミドルウェアのみ）。

**ルーターと認可**（登録順は上から。`cp` / `public` を AP より先に登録する。01 §10.1）

| プレフィックス | タグ | 実装 | ルーター全体に適用するもの |
| --- | --- | --- | --- |
| `/api/auth` | `auth` | `main_app/route/auth/` | なし（BFF のフロー）。status / logout は OpenAPI に載せる。login / callback / dev-login はブラウザを遷移させるリダイレクトのため載せない（`include_in_schema=False`） |
| `/api/v1/cp` | `cp` | `control_plane_app/apiapp.py` | `require_cp_roles("saas_admin", "saas_viewer")` → `require_csrf_protection`。変更系のエンドポイントはさらに `require_cp_roles("saas_admin")` |
| `/api/v1/public` | `public` | `main_app/route/public/apiapp.py` | なし |
| `/api/v1` | `app` | `main_app/route/v1/apiapp.py` | `get_app_tenant_context` → `require_csrf_protection` → `require_active_app_user`（セッションのユーザーが AP で有効か。下記）。各エンドポイントのロール確認はこの後 |

**エンドポイント**（`GET /openapi.json` が契約の正。ここは一覧）

| メソッド | パス | 認可 | 概要 |
| --- | --- | --- | --- |
| GET | `/api/auth/app/status` | AP セッション | `AppAuthStatus`: `{authenticated, plane: "app", tenant_code, user: {sub, preferred_username, email, roles}}`。未認証・CP のセッションのみは 401。レルム名・クライアント ID・`tenant_id` は返さない |
| GET | `/api/auth/cp/status` | CP セッション | `CpAuthStatus`: `{authenticated, plane: "cp", user}`。未認証・AP のセッションのみは 401 |
| POST | `/api/auth/app/logout` / `cp/logout` | なし（CSRF 対策のみ） | `LogoutResult`: `{logout_url}`（Keycloak のログアウト URL。完了後は 5.2 の遷移先へ）。プレーンの Cookie を削除する。セッションが無くても 200。CSRF の不足は 403 |
| GET | `/api/v1/me` | AP セッション | テナント（`id`, `tenant_code`）とユーザー（`id`, `username`, `email`, `roles`）。`user.id` は **AP のユーザー ID（`t_user.id`）**で、IdP の `sub` ではない（`users` の `id`・組織のメンバー ID と同じ値） |
| GET | `/api/v1/users` | `tenant_admin` / `member` | 一覧。カーソル方式（`limit` / `cursor`）、`sort`（`display_name` 既定 / `created_at`、先頭 `-` で降順）、`is_active`。無効化されたユーザーも含む。ロールは含まない。`include_total` は無い（`total` は常に `null`） |
| POST | `/api/v1/users` | `tenant_admin` | 201、`Location` と `ETag`、`Cache-Control: no-store`。`{user, credentials: {username, temporary_password}}`。一時パスワードは一度だけ返す（保存しない・ログに出さない）。メール・ユーザー名の重複は 409、Keycloak の失敗は 502（AP にはユーザーを作らない） |
| GET | `/api/v1/users/{id}` | `tenant_admin` / `member` | ロール付きの詳細（Keycloak に問い合わせる。失敗は 502）。`ETag`。他テナント・存在しないユーザーは同じ 404 |
| PATCH | `/api/v1/users/{id}` | `tenant_admin` | `first_name` + `last_name`（両方）/ `roles` / `is_active`（送った項目だけ。`null` は 422）。`If-Match` 必須（428 / 412）。200 とユーザー（ロールは含まない）、新しい `ETag`。自分自身の無効化・`tenant_admin` の解除は 409。無効化時の動きは 5.1 |
| GET | `/api/v1/organizations` | `tenant_admin` / `member` | 一覧（論理削除を除く）。カーソル方式、`sort`（`name` 既定 / `created_at`）。メンバーは含まない |
| POST | `/api/v1/organizations` | `tenant_admin` | 201、`Location` と `ETag`。組織名の重複（大文字小文字を区別しない）は 409 |
| GET | `/api/v1/organizations/{id}` | `tenant_admin` / `member` | 詳細。`member_ids`（ユーザー ID）を含む。`ETag`。他テナント・存在しない・論理削除済みは同じ 404 |
| PATCH | `/api/v1/organizations/{id}` | `tenant_admin` | 組織名の変更。`If-Match` 必須。200 と組織、新しい `ETag` |
| DELETE | `/api/v1/organizations/{id}` | `tenant_admin` | 論理削除。`If-Match` 必須。204（本文なし） |
| PUT | `/api/v1/organizations/{id}/members` | `tenant_admin` | `{user_ids}` の全置換。`If-Match` 必須。200 と組織（`member_ids` 付き）、新しい `ETag`。テナント内に存在しないユーザー（他テナントを含む）は 422（`invalid_organization_members`、拡張メンバー `user_ids`） |
| GET | `/api/v1/cp/tenants` | CP 参照 | 一覧。カーソル方式（`limit` / `cursor` / `include_total`）、`sort`（`created_at` 既定 `-created_at` / `tenant_code` / `name`）、`status`（カンマ区切り）。直近の日次メトリクスのユーザー数と、テーマ固有の主要指標（`primary_metrics`: `{metric_key, value, date}` の配列。`modules.tenant_metrics.registry.theme_primary_metric_keys()` の順。ToDo は `todo_count`。集計前は `value` / `date` が `null`）を含む |
| POST | `/api/v1/cp/tenants` | `saas_admin` | 同期払い出し。201、`Location` と `ETag`。一時パスワードを本文で一度だけ返し、`Cache-Control: no-store` |
| GET | `/api/v1/cp/tenants/{id}` | CP 参照 | 詳細と払い出し履歴。`ETag` |
| POST | `/api/v1/cp/tenants/{id}/suspend` / `resume` | `saas_admin` | `If-Match` 必須（無ければ 428、不一致は 412）。200 とテナント、新しい `ETag` |
| DELETE | `/api/v1/cp/tenants/{id}` | `saas_admin` | 削除要求（`PENDING_DELETION`）。`If-Match` 必須。物理削除は猶予期間後の定期ジョブ |
| POST | `/api/v1/cp/tenants/{id}/provisioning/retry` | `saas_admin` | 再実行。初期管理者を本文で受け取る（台帳に保存していないため）。`If-Match` は任意。一時パスワードは新しい値を一度だけ返す |
| GET | `/api/v1/cp/tenants/{id}/metrics?from=&to=` | CP 参照 | `t_tenant_daily_metric` の推移（既定は直近 30 日、最大 366 日）。データが無ければ `items` は空。値は 10 進数の文字列 |
| GET | `/api/v1/cp/metrics/summary` | CP 参照 | 状態ごとのテナント数と、指標ごとの最新値の合計（削除済みを除く） |
| GET | `/api/v1/public/health/live` | なし | プロセスの生存のみ |
| GET | `/api/v1/public/health/ready` | なし | CP DB・AP DB・Redis に接続できるか。失敗は 503 |
| GET | `/api/v1/public/tenants/{tenant_code}` | なし | `{tenant_code, status}` のみ。存在しない・削除済み・形式不正・予約語は区別せず 404 |

**AP の API の認可と規約**（`main_app/route/v1/`）

- 参照は `tenant_admin` / `member`、変更は `tenant_admin`（`require_app_roles`）。ロール確認はルーター全体の依存関数（テナント → CSRF → 有効確認）の後に評価するため、member の変更は本文の検証より先に 403 になる
- **有効確認（`require_active_app_user`。PF-USR-03、05 #32）**: 各リクエストで `require_active_session_user` を呼ぶ（`t_user` を `sub` で 1 回 SELECT。キャッシュしない）。`UserDeactivatedError`（401 `user_deactivated`）/ `UserNotSyncedError`（401 `user_not_synced`）の場合は Redis のセッションを削除（`modules.auth.session.delete_session`）して 401 にする。以降の同じ Cookie は `session_expired`（401）。`/me` を含む `/api/v1` 全体が対象（`cp` / `public` は対象外）。AP の DB セッションは同じリクエスト内で共有する
- 変更系の `PATCH` / `PUT` / `DELETE` は `If-Match: "<version>"` 必須。OpenAPI でも必須ヘッダー（`If-Match`）として出る
- 一覧のカーソルは `main_app/route/v1/paging.py`（リポジトリの `(キー, id)` を `modules/api_common/pagination` の形式にする）。`sort` や `cursor` が不正なら 422
- サービスの例外は `main_app/problems.py` で Problem Details にする（`app.py` で `register_ap_exception_handlers`）。404 は他テナント・存在しないを区別しない
- テストでの差し替え: `main_app/route/v1/deps.py` の `get_user_service`（Keycloak の管理クライアントのフェイク）、`require_active_app_user`

**エラー**（`modules/errors`。03 §2）

- `application/problem+json`（RFC 9457）。`type` / `title` / `status` / `detail` / `instance` / `code` / `request_id` / `errors`（`{field, code, message}`）。`title` / `detail` は日本語の固定文言で、`HTTPException.detail` の文字列はそのまま返さない（`modules/errors/catalog.py` の対応表で `code` にする。表に無いものはステータスの既定の文言）
- ルーターからは `ProblemError` を送出する。`HTTPException`・`RequestValidationError`（422、`errors` に項目ごとの詳細）・払い出しサービスの例外（`control_plane_app/problems.py`）・Redis / DB の接続失敗（503）・想定外の例外（500。内容は返さずログに残す）を変換する
- AP のユーザー・組織管理の `code`（`main_app/problems.py`）: 422 `invalid_user_input` / `invalid_user_role` / `invalid_organization_input` / `invalid_organization_members`、404 `user_not_found` / `organization_not_found`、409 `user_already_exists` / `organization_name_already_exists` / `user_self_modification_forbidden`（拡張メンバー `operation`）、412 `user_version_conflict` / `organization_version_conflict`、502 `identity_provider_operation_failed`、401 `user_deactivated` / `user_not_synced`
- AP と CP で 401 / 403 / 404 の形は同じ。AP の 403 は `tenant_inactive`（停止中・削除要求中）とそれ以外（`tenant_unavailable`。存在有無を推測させないため集約）に分ける
- 払い出しの失敗（502）は拡張メンバー `tenant_id` / `step` を返す（`tenant_id` で再実行できる）。状態遷移の不正（409）は `operation` / `current_status` を返す
- OpenAPI は後処理で、エラー応答を `application/problem+json`・`ProblemDetails` にそろえる（`modules/errors/openapi.py`）
- `/api/auth/callback` は例外を Problem Details で返さず、ログイン画面へ `?error=<code>` で 302 する（5.2）

**OpenAPI での認証・CSRF の表現**

- セッション Cookie はセキュリティスキーム（`AppSession`: cookie `rf_sid_app`、`CpSession`: cookie `rf_sid_cp`）。各操作の `security` で必要なセッションが分かる。cookie パラメータとしては出さない
- `X-Requested-With`（値は `rf-stack` のみ）は変更系メソッドの必須ヘッダーとして載せ、参照系には載せない（`modules/auth/csrf.py` の `install_csrf_openapi`）。`Origin` はブラウザが付けるため説明文にだけ書く
- 入力が `X-Requested-With` だけの操作（ログアウトなど）からは、FastAPI が付ける 422 を取り除く

**リクエスト ID**: `X-Request-ID` を受け取り（形式が不正・無ければ UUIDv7 を生成）、レスポンスヘッダー・Problem Details の `request_id`・監査ログに使う（`modules/errors/request_id.py`）。

**規約の部品**（`modules/api_common`）: 日時は UTC に正規化して `Z` 付きで出力（`UtcDatetime`）、カーソルは base64url の JSON（並び替えの指定・キーの値・`id`。並び替えが変わると 422）、`ETag: "<version>"` / `If-Match`（形式不正は 400）。

**公開 API の判断**

- `health/ready` は CP DB・AP DB（`SELECT 1`）と Redis（`PING`）を確認する。**Keycloak は含めない**。停止してもログイン済みのセッションは使えるため、含めると IdP の障害で全 API がトラフィックから外れて影響が広がる（Keycloak の死活は監視 04 で扱う）。確認は並列で、合計 3 秒で打ち切る
- `public/tenants/{tenant_code}` のレート制限は、Redis の固定ウィンドウによる IP 単位の簡易実装（既定 60 回 / 60 秒。`PUBLIC_TENANT_LOOKUP_RATE_LIMIT` で変更、`0` で無効、`PUBLIC_TENANT_LOOKUP_RATE_WINDOW_SECONDS`）。超過は 429（`Retry-After`）。Redis 障害時は制限せず通す（fail-open）。**リバースプロキシの背後では `X-Forwarded-For` の設定と uvicorn の `--proxy-headers --forwarded-allow-ips` が必要**で、無いと全クライアントが同じ IP に見えて 1 つの枠を共有する（本番投入前に infra で設定する）

---

## 6. React

### 6.1 ディレクトリ構成

```
react_app/src/
  main.tsx                  # エントリ
  routes/                   # トップレベルルーター（/, /cp/*, /:tenantCode/*）
  shared/                   # UI 部品、fetch ラッパー（FetchComponents）、テーマ。プレーン固有ロジックを含めない
  main_app/                 # アプリケーションプレーン
    routes.tsx
    auth/                   # AppAuthProvider（/api/auth/app/*）
    api/
    pages/
  control_plane_app/        # コントロールプレーン
    routes.tsx
    auth/                   # ControlPlaneAuthProvider（/api/auth/cp/*）
    api/
    pages/
```

- バックエンドと同じ `main_app` / `control_plane_app` の名前を使う
- 現在の `pages/authentication`、`store/AuthNZ`、`utils/libs` は、それぞれ各プレーンの `auth/` と `shared/` に移行する。`sample/` は基盤の実装が進んだ段階で削除する
- 各プレーンの `routes.tsx` は `React.lazy` で遅延読み込みする

### 6.2 API 呼び出し

- 認証状態は Cookie で運ばれるため、フロントはトークンを扱わない
- fetch ラッパーで、変更系メソッドに `X-Requested-With: rf-stack` を必ず付与する
- 401 を受けたら各プレーンのログイン画面へ、403 はエラー画面へ遷移する
- API の型は OpenAPI から生成し（`api-contract-sync` が整合を確認する）、手書きの型と二重管理しない
- CP のデータ取得は、エンドポイント関数・エラー分類を `control_plane_app/api/`（`tenants.ts` / `metrics.ts` / `errors.ts`）に、画面が使うフックを `control_plane_app/tenants/`・`control_plane_app/metrics/` に置き、`pages/` からは fetch を直接呼ばない

### 6.3 Vite

- `base` は `/`（`VITE_APP_ROUTER_BASE`）のまま。ビルド成果物のアセットは `build.assetsDir`（既定 `assets`）配下に出力され、予約語 `/assets` と一致する
- `public/` の静的ファイル（`favicon.ico`, `icon.png` 等）はドットを含むため、テナントコードと衝突しない
- `/api` を `fastapi_app` に proxy する（`/` を proxy 対象にしない）

---

## 7. 開発用ログインとシード

### 7.1 シードデータ

| 種別 | 内容 |
| --- | --- |
| CP | `control-plane` レルム、`saas_admin` と `saas_viewer` のユーザー各 1 |
| テナント | `alpha`（`tenant-alpha`）、`beta`（`tenant-beta`）。払い出し処理と同じコードで作成する |
| ユーザー | 各テナントに `tenant_admin` 1、`member` 2 |

- シードは CP の払い出しサービスを CLI から呼び出して作成する（Keycloak を直接いじるスクリプトを別に持たない）
- 認証情報（開発用）は `fastapi_app` 側の 1 箇所（`modules/auth/dev_profiles.py`）に定義し、開発用ログインのプロファイルと共有する

```bash
make d-run SERVICE=fastapi_app CMD="uv run python -m control_plane_app.seed"
```

- 何度実行してもよい（冪等）。`control-plane` レルムと CP のユーザーを反映し、各テナントは台帳に無ければ `onboard`、`FAILED` / `PROVISIONING` なら `retry`、`ACTIVE` ならスキップする。その後、各テナントのユーザーを開発用パスワード（一時パスワードではない）で作成・更新する
- 初期管理者は各テナントの `tenant_admin`（`alpha-admin` / `beta-admin`）。払い出しで設定された一時パスワードは、直後のユーザー作成で開発用パスワードに置き換わる
- `APP_ENV=development` が明示的に設定されていない場合は実行を拒否する（終了コード 2）
- 停止中・削除要求中などのテナントは触らない（警告のみ）。作り直す場合は台帳と Keycloak の両方を消してから再実行する

### 7.2 開発用ログイン

```
GET /api/auth/dev-login?as=<profile>&next=<path>
```

| `as` | ログイン先 |
| --- | --- |
| `cp-admin` | `control-plane`（`saas_admin`） |
| `cp-viewer` | `control-plane`（`saas_viewer`） |
| `alpha-admin` | `tenant-alpha`（`tenant_admin`） |
| `alpha-member` | `tenant-alpha`（`member`） |
| `beta-member` | `tenant-beta`（`member`）。クロステナントの確認用 |

- `APP_ENV=development` かつ `AUTH_DEV_LOGIN_ENABLED=true` のときのみルートを登録する（現行どおり）
- Direct Access Grant で本物のトークンを取得し、通常のコールバックと同じ内容のセッションを作る（現行どおり）
- AP のプロファイルは、通常のコールバックと同じくレルムをレジストリで ACTIVE なテナントに解決して `tenant_id` クレームとの一致を確認し（未登録・非 ACTIVE・テナントコードの食い違いは 403）、セッションを作る前にユーザー同期を行う（5.2）。シードユーザーの AP のユーザー行は、各ユーザーの最初のログインで作られる
- プロファイルと開発用の認証情報は `fastapi_app/src/modules/auth/dev_profiles.py` に定義する（`as` 省略時は `alpha-admin`）。旧プロファイル `default`（`tenant-a` / `user001`）は、テナントコード `a` が 01 の形式に合わないため削除した

---

## 8. 現状からの移行一覧

| 項目 | 現状 | 目標 |
| --- | --- | --- |
| 認証のログイン開始 | （済）`/api/auth/app/login?tenant_code=`（レジストリで解決）、`/api/auth/cp/login` | — |
| 認証の遷移先 | （済）01 の 11.1 のルーティングに合わせた（5.2。旧 `/button`・`/login?error=` は廃止）。コールバックの失敗は JSON ではなくログイン画面へのリダイレクト | — |
| セッション Cookie | （済）`rf_sid_app` / `rf_sid_cp` | — |
| セッションのユーザー情報 | （済）`sub`, `preferred_username`, `email`, `realm`, `plane`, `roles`、AP のみ `tenant_id` | — |
| テナント部品の組み込み | （済）`modules/tenancy` を作成し、`app_db` 用の sessionmaker にリスナーを登録 | （済）AP ルーター（`/api/v1`）に `AppTenantContextDep` を適用 |
| CP の API | （済）`/api/v1/cp/*`。旧 `/control_plane/*` と `control_plane_app/api_tenant/` は削除（React からの呼び出しは無かった） | — |
| 公開 API | （済）`/api/v1/public/*`（ヘルスチェック、テナント存在確認） | — |
| AP の API | （済）`/api/v1/me`、`/api/v1/users`、`/api/v1/organizations`（01 §10.2。`user.id` は `t_user.id`） | — |
| AP のユーザー同期・組織管理 | （済）サービス層（5.1 の `main_app/services/`）、ログイン処理への `sync_user_on_login`（5.2）、`/api/v1` への有効確認 `require_active_app_user`（PF-USR-03。5.6）。払い出し時の AP の初期データはログイン完了時に AP が作る（05 #31） | — |
| エラー形式 | （済）RFC 9457 Problem Details（`modules/errors`）。`/api/auth/*` と旧サンプルも同じハンドラで変換される | — |
| CSRF 対策 | （済）依存関数 `require_csrf_protection`（`/api/v1`、`/api/v1/cp`、ログアウトに適用） | — |
| テナント台帳 | （済）01 の 9.5 に沿って改訂（4.6） | （済）CP API（`/api/v1/cp/*`）から利用 |
| DB ロール | （済）プレーン・用途毎に分離 | 既存の開発環境は `make d-reset-db` で作り直す |
| Alembic | （済）プレーン毎の 2 環境、`create_all()` を廃止 | — |
| Keycloak セットアップ | （済）Python の `modules/keycloak_admin` | （済）払い出しサービスから利用 |
| デモ用 API | `/api/demo/login`、`rest_sample`、`sample` | 基盤の実装が進んだ段階で削除 |
