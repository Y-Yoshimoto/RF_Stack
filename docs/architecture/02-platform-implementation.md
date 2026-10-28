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
      runner.py               # APScheduler の起動とジョブ登録のみ
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
| `control_plane_app/jobs/` | `provisioning_reaper` / `tenant_purge` の本体（`python -m control_plane_app.jobs <job_name>` でも実行できる）。スケジューラへの登録は未実装 |
| `control_plane_app/seed.py` | 開発用シード（7.1） |

  使い方と守ることは `tenant-provisioning` スキルの 3 章を参照する
- 例外: AP のテナントレジストリ参照は `modules/tenancy/registry.py` の読み取り専用インターフェース経由
- 各層の担当エージェント: ルーター・スキーマ → `fastapi-api-schema`、サービス・共通部品 → `fastapi-domain`、モデル・マイグレーション → `postgres-schema`、テスト → `fastapi-pytest`、認証 → `auth-keycloak`

### 5.2 認証（BFF）

| 項目 | 実装 |
| --- | --- |
| セッション Cookie | AP: `rf_sid_app`、CP: `rf_sid_cp`。`HttpOnly`、`SameSite=Lax`、`Secure` は `APP_ENV` から導出。値は `itsdangerous` でプレーン毎の salt を使って署名 |
| セッションストア | Redis。キーは `session:app:{sid}` / `session:cp:{sid}`、TTL は `SESSION_TTL_SECONDS` |
| セッションの内容 | `plane`, `realm`, `tenant_id` / `tenant_code`（AP のみ）, `user`, `tokens`。`user` は `sub`, `preferred_username`, `email`, `realm`, `plane`, `roles`（プレーンの許可リストにあるレルムロールのみ）で、AP のみ `tenant_id` を加える |
| 認可リクエストの一時状態 | Redis `auth_state:{state}`（TTL 300 秒）に `plane`, `realm`, `code_verifier`, `nonce` |
| トークン検証 | レルム毎の JWKS を `PyJWKClient` でキャッシュ。issuer は内部・外部 URL の両方を許可（`KC_HOSTNAME` 固定前提）。アクセストークンはアクセスのたびに期限を確認し、切れていればサーバー側で更新する |
| 認証依存関数 | `modules/auth/dependency.py` の `get_current_app_user` / `get_current_cp_user`（未認証・別プレーンのセッションは 401）、`require_app_roles` / `require_cp_roles`（ロール不足は 403）。AP ルーターはさらに `AppTenantContextDep`（`modules/tenancy/app_dependency.py`。レジストリ照合、停止中・不一致は 403）を適用する |
| CSRF | ミドルウェアではなく**依存関数** `require_csrf_protection`（`modules/auth/csrf.py`）。変更系メソッド（POST / PUT / PATCH / DELETE）で `X-Requested-With: rf-stack` と、許可したオリジン（`FRONTEND_URL` と `CSRF_TRUSTED_ORIGINS`）に一致する `Origin` を検証し、不足は 403。参照系は素通りするため、ルーター単位で付ける（`/api/v1` と `/api/v1/cp` のルーターに適用済み） |

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
- フロントは予約語リストを持たない。静的ルートを `/:tenantCode/*` より先に定義し、それ以外の第 1 セグメントは公開のテナント存在確認 API（予約語は 404）で判定する

### 5.5 定期実行

- `scheduler/runner.py` が FastAPI の lifespan で APScheduler を起動・停止する
- 環境変数 `SCHEDULER_ENABLED`（既定 `true`）で無効化できる。複数ワーカー構成では 1 つ以外で無効化するか、advisory lock に任せる
- ジョブ実行時に `pg_try_advisory_lock(hashtext('<job_name>'))` を CP DB で取得し、取れなければスキップする
- ジョブ本体は `control_plane_app/jobs/` の普通の関数とし、CLI からも実行できる

### 5.6 API 層（ルーティング・エラー・規約）

実装は `app.py`（ルーターのマウント、lifespan、例外ハンドラ、リクエスト ID のミドルウェアのみ）。

**ルーターと認可**（登録順は上から。`cp` / `public` を AP より先に登録する。01 §10.1）

| プレフィックス | タグ | 実装 | ルーター全体に適用するもの |
| --- | --- | --- | --- |
| `/api/auth` | `auth` | `main_app/route/auth/` | なし（BFF のフロー。OpenAPI には出さない） |
| `/api/v1/cp` | `cp` | `control_plane_app/apiapp.py` | `require_cp_roles("saas_admin", "saas_viewer")` → `require_csrf_protection`。変更系のエンドポイントはさらに `require_cp_roles("saas_admin")` |
| `/api/v1/public` | `public` | `main_app/route/public/apiapp.py` | なし |
| `/api/v1` | `app` | `main_app/route/v1/apiapp.py` | `AppTenantContextDep` → `require_csrf_protection` |

**エンドポイント**（`GET /openapi.json` が契約の正。ここは一覧）

| メソッド | パス | 認可 | 概要 |
| --- | --- | --- | --- |
| GET | `/api/v1/me` | AP セッション | テナント（`id`, `tenant_code`）とユーザー（`id`, `username`, `email`, `roles`） |
| GET | `/api/v1/cp/tenants` | CP 参照 | 一覧。カーソル方式（`limit` / `cursor` / `include_total`）、`sort`（`created_at` 既定 `-created_at` / `tenant_code` / `name`）、`status`（カンマ区切り）。直近の日次メトリクスのユーザー数を含む |
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

users / organizations（01 §10.2）は AP のテーブルを作成した後に追加する。

**エラー**（`modules/errors`。03 §2）

- `application/problem+json`（RFC 9457）。`type` / `title` / `status` / `detail` / `instance` / `code` / `request_id` / `errors`（`{field, code, message}`）。`title` / `detail` は日本語の固定文言で、`HTTPException.detail` の文字列はそのまま返さない（`modules/errors/catalog.py` の対応表で `code` にする。表に無いものはステータスの既定の文言）
- ルーターからは `ProblemError` を送出する。`HTTPException`・`RequestValidationError`（422、`errors` に項目ごとの詳細）・払い出しサービスの例外（`control_plane_app/problems.py`）・Redis / DB の接続失敗（503）・想定外の例外（500。内容は返さずログに残す）を変換する
- AP と CP で 401 / 403 / 404 の形は同じ。AP の 403 は `tenant_inactive`（停止中・削除要求中）とそれ以外（`tenant_unavailable`。存在有無を推測させないため集約）に分ける
- 払い出しの失敗（502）は拡張メンバー `tenant_id` / `step` を返す（`tenant_id` で再実行できる）。状態遷移の不正（409）は `operation` / `current_status` を返す
- OpenAPI は後処理で、エラー応答を `application/problem+json`・`ProblemDetails` にそろえる（`modules/errors/openapi.py`）

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
- プロファイルと開発用の認証情報は `fastapi_app/src/modules/auth/dev_profiles.py` に定義する（`as` 省略時は `alpha-admin`）。旧プロファイル `default`（`tenant-a` / `user001`）は、テナントコード `a` が 01 の形式に合わないため削除した

---

## 8. 現状からの移行一覧

| 項目 | 現状 | 目標 |
| --- | --- | --- |
| 認証のログイン開始 | （済）`/api/auth/app/login?tenant_code=`（レジストリで解決）、`/api/auth/cp/login` | — |
| セッション Cookie | （済）`rf_sid_app` / `rf_sid_cp` | — |
| セッションのユーザー情報 | （済）`sub`, `preferred_username`, `email`, `realm`, `plane`, `roles`、AP のみ `tenant_id` | — |
| テナント部品の組み込み | （済）`modules/tenancy` を作成し、`app_db` 用の sessionmaker にリスナーを登録 | （済）AP ルーター（`/api/v1`）に `AppTenantContextDep` を適用 |
| CP の API | （済）`/api/v1/cp/*`。旧 `/control_plane/*` と `control_plane_app/api_tenant/` は削除（React からの呼び出しは無かった） | — |
| 公開 API | （済）`/api/v1/public/*`（ヘルスチェック、テナント存在確認） | — |
| AP の API | （済）`/api/v1/me`。users / organizations は AP のテーブルの作成後 | `/api/v1/users`、`/api/v1/organizations`（01 §10.2） |
| エラー形式 | （済）RFC 9457 Problem Details（`modules/errors`）。`/api/auth/*` と旧サンプルも同じハンドラで変換される | — |
| CSRF 対策 | （済）依存関数 `require_csrf_protection`（`/api/v1`、`/api/v1/cp`、ログアウトに適用） | — |
| テナント台帳 | （済）01 の 9.5 に沿って改訂（4.6） | （済）CP API（`/api/v1/cp/*`）から利用 |
| DB ロール | （済）プレーン・用途毎に分離 | 既存の開発環境は `make d-reset-db` で作り直す |
| Alembic | （済）プレーン毎の 2 環境、`create_all()` を廃止 | — |
| Keycloak セットアップ | （済）Python の `modules/keycloak_admin` | （済）払い出しサービスから利用 |
| デモ用 API | `/api/demo/login`、`rest_sample`、`sample` | 基盤の実装が進んだ段階で削除 |
