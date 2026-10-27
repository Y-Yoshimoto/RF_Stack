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
- CP の初期リビジョンは `0001_create_t_tenant`（既存の `t_tenant` をそのまま作成）

### 4.5 プレーン間アクセスの実装

| 01 の依存 | 接続 | 実装 |
| --- | --- | --- |
| AP → CP（レジストリ参照） | `cp_registry_reader` で `control_plane_db` の `v_tenant_registry` | `modules/tenancy/registry.py` の `TenantRegistry`。プロセス内 TTL キャッシュ（30 秒） |
| CP → AP（集計・物理削除） | `app_cp_agent` で `app_db` | テナント毎に `set_config` でコンテキストを切り替える。CP のリポジトリ層に閉じ込める |

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
      logging/                # 構造化ログ（予定）
      errors/                 # Problem Details の例外とハンドラ（予定）
    control_plane_app/        # コントロールプレーン
      api_*/                  # /api/v1/cp ルーター（fastapi-api-schema）
      services/               # 払い出し・メトリクス等（fastapi-domain）
      repositories/           # DB アクセス（AP DB への集計・物理削除もここに閉じ込める）
      models/                 # CP の SQLModel（postgres-schema）
      jobs/                   # 定期ジョブ本体（APScheduler に依存しない関数）
    main_app/                 # アプリケーションプレーン
      route/                  # /api/v1 ルーター、/api/auth ルーター
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
- 例外: AP のテナントレジストリ参照は `modules/tenancy/registry.py` の読み取り専用インターフェース経由
- 各層の担当エージェント: ルーター・スキーマ → `fastapi-api-schema`、サービス・共通部品 → `fastapi-domain`、モデル・マイグレーション → `postgres-schema`、テスト → `fastapi-pytest`、認証 → `auth-keycloak`

### 5.2 認証（BFF）

| 項目 | 実装 |
| --- | --- |
| セッション Cookie | AP: `rf_sid_app`、CP: `rf_sid_cp`。`HttpOnly`、`SameSite=Lax`、`Secure` は `APP_ENV` から導出。値は `itsdangerous` で署名 |
| セッションストア | Redis。キーは `session:app:{sid}` / `session:cp:{sid}`、TTL は `SESSION_TTL_SECONDS` |
| セッションの内容 | `plane`, `realm`, `tenant_id`, `tenant_code`（AP のみ）, `user`（`sub`, `user_id`, `roles`）, `tokens` |
| 認可リクエストの一時状態 | Redis `auth_state:{state}`（TTL 300 秒）に `plane`, `realm`, `code_verifier`, `nonce` |
| トークン検証 | レルム毎の JWKS を `PyJWKClient` でキャッシュ。issuer は内部・外部 URL の両方を許可（`KC_HOSTNAME` 固定前提） |
| 認証依存関数 | AP ルーター: `require_app_session` → `require_tenant_context`、CP ルーター: `require_cp_session` → ロール確認 |
| CSRF | 変更系メソッドで `X-Requested-With: rf-stack` ヘッダーと `Origin` の一致を検証するミドルウェア |

現状の実装（`/api/auth/login?realm=`、単一 Cookie `rf_sid`）は、上記のプレーン別構成に移行する。

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

- 正は `modules/tenancy` 配下の定数（バックエンド）とする。テナント作成 API が検証する
- フロントは予約語リストを持たない。静的ルートを `/:tenantCode/*` より先に定義し、それ以外の第 1 セグメントは公開のテナント存在確認 API（予約語は 404）で判定する

### 5.5 定期実行

- `scheduler/runner.py` が FastAPI の lifespan で APScheduler を起動・停止する
- 環境変数 `SCHEDULER_ENABLED`（既定 `true`）で無効化できる。複数ワーカー構成では 1 つ以外で無効化するか、advisory lock に任せる
- ジョブ実行時に `pg_try_advisory_lock(hashtext('<job_name>'))` を CP DB で取得し、取れなければスキップする
- ジョブ本体は `control_plane_app/jobs/` の普通の関数とし、CLI からも実行できる

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
- 認証情報（開発用）は `fastapi_app` 側の 1 箇所に定義し、開発用ログインのプロファイルと共有する

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
- 現状のプロファイル（`default` → `tenant-a` / `user001`）は、シード整備時に上表へ置き換える。テナントコード `a` は 3 文字未満で 01 の形式に合わないため、`tenant-a` は使い続けない

---

## 8. 現状からの移行一覧

| 項目 | 現状 | 目標 |
| --- | --- | --- |
| 認証のログイン開始 | `/api/auth/login?realm=`（任意のレルム名を受け付ける） | `/api/auth/app/login?tenant_code=`（レジストリで解決）、`/api/auth/cp/login` |
| セッション Cookie | `rf_sid`（1 つ） | `rf_sid_app` / `rf_sid_cp` |
| セッションのユーザー情報 | `sub`, `preferred_username`, `email`, `realm` のみ | トークンの `tenant_id` クレームと `roles` を追加（`RegistryTenantResolver` が必要とする） |
| テナント部品の組み込み | （済）`modules/tenancy` を作成 | `app_db` 用 `DBConnector` に `install_tenant_guc_listener` を登録、AP ルーターに `create_tenant_context_dependency` を適用 |
| CP の API | `/control_plane/tenant/*`（`/api` 外で Vite proxy を通らない） | `/api/v1/cp/*` |
| テナント台帳 | `t_tenant`（`isenabled`, `claim`, `industry` 等） | 01 の 9.5 に沿って改訂 |
| DB ロール | （済）プレーン・用途毎に分離 | 既存の開発環境は `make d-reset-db` で作り直す |
| Alembic | （済）プレーン毎の 2 環境、`create_all()` を廃止 | — |
| Keycloak セットアップ | （済）Python の `modules/keycloak_admin` | 払い出しサービスから利用 |
| デモ用 API | `/api/demo/login`、`rest_sample`、`sample` | 基盤の実装が進んだ段階で削除 |
