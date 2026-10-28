# main_app/route

FastAPI アプリケーションのルーティング定義をサブパッケージとして管理するディレクトリ。

各サブパッケージがルーターを定義し、`app.py` で `include_router` によって登録される。

---

## ディレクトリ構成

```
route/
├── auth/                   # /api/auth (BFF)
│   ├── __init__.py         # router を公開
│   ├── apiapp.py           # OIDC 認証エンドポイントの実装 (AP / CP)
│   ├── dev_login.py        # 開発用ログインバイパス
│   └── login_sync.py       # AP のログイン完了時のユーザー同期の呼び出し (コールバック・開発用ログインが共有)
├── public/                 # /api/v1/public (認証なし)
│   ├── apiapp.py           # api_health / api_tenant_lookup を束ねる
│   ├── api_health/         # health/live, health/ready
│   ├── api_tenant_lookup/  # tenants/{tenant_code} (存在確認)
│   ├── rate_limit.py       # 存在確認の簡易レート制限 (Redis)
│   └── redis_client.py     # 短いタイムアウトの Redis クライアント
├── v1/                     # /api/v1 (AP。AP セッション + テナントコンテキスト + CSRF + ユーザーの有効確認をルーター全体に適用)
│   ├── apiapp.py
│   ├── deps.py             # require_active_app_user、tenant_admin 要求、サービスの依存関数
│   ├── paging.py           # 一覧のカーソル・sort の解釈
│   ├── openapi.py          # 成功レスポンスのヘッダー (ETag / Location / Cache-Control) の OpenAPI 定義
│   ├── api_me/             # GET /api/v1/me
│   ├── api_users/          # /api/v1/users
│   └── api_organizations/  # /api/v1/organizations (members 含む)
└── sample/                 # サンプル (基盤の実装が進んだ段階で削除)
```

`/api/v1/cp` (CP) は `control_plane_app/apiapp.py`。`app.py` では `cp` / `public` を AP (`v1`) より先に登録する
(`/api/v1/cp`・`/api/v1/public` は予約パス。01 §10.1)。各エンドポイントの一覧とエラー形式は
`docs/architecture/02-platform-implementation.md` の 5.6 を参照。

---

## auth — KeyCloak 認証ルーター (BFF、プレーン別)

**prefix**: `/api/auth`

KeyCloak との OIDC Authorization Code Flow (PKCE) を実装する BFF エンドポイント群。
仕様の正は `docs/architecture/01-platform-concepts.md` §7・§10 と `02-platform-implementation.md` §3・§5.2。

React は Vite proxy 経由で全て `http://localhost:5173/api/auth/...` にアクセスし、
FastAPI がブラウザの代わりに KeyCloak と通信する。ブラウザはトークンを持たない。

### エンドポイント一覧

| メソッド | パス | 概要 |
|---|---|---|
| `GET` | `/api/auth/app/login?tenant_code=` | AP の認可リクエストを開始する。`tenant_code` をテナントレジストリで ACTIVE なテナントのレルムに解決する。利用できないテナントは理由を区別せず `/?error=tenant_unavailable` へ |
| `GET` | `/api/auth/cp/login` | CP の認可リクエストを開始する (レルム `control-plane`) |
| `GET` | `/api/auth/callback` | 認可コードをトークンに交換してセッションを確立する (state からプレーン・レルムを復元)。成功は AP `/{tenant_code}/`・CP `/cp/` へ、失敗は JSON を返さずログイン画面へ `?error=<code>` で 302 |
| `GET` | `/api/auth/app/status` / `/api/auth/cp/status` | セッションを検証してユーザー情報を返す (レルム名・クライアント ID は返さない) |
| `POST` | `/api/auth/app/logout` / `/api/auth/cp/logout` | プレーンのセッションを削除し、KeyCloak のログアウト URL を JSON (`{logout_url}`) で返す。`X-Requested-With: rf-stack` と `Origin` が必須 |
| `GET` | `/api/auth/dev-login?as=&next=` | 開発用ログイン (`APP_ENV=development` かつ `AUTH_DEV_LOGIN_ENABLED=true` のときのみ登録) |

> status / logout は OpenAPI に載せる (応答の型 `AppAuthStatus` / `CpAuthStatus` / `LogoutResult` と 401 / 403 の Problem Details)。
> login / callback / dev-login はブラウザを遷移させるリダイレクトのため `include_in_schema=False`。
> 遷移先とコールバックのエラーコードの正は `modules/auth/redirects.py` と `docs/architecture/02-platform-implementation.md` §5.2。

### プレーン

| | AP | CP |
|---|---|---|
| Cookie | `rf_sid_app` | `rf_sid_cp` |
| Redis キー | `session:app:{sid}` | `session:cp:{sid}` |
| レルム | `tenant-{tenant_code}` (レジストリで解決) | `control-plane` |
| クライアント | `KEYCLOAK_CLIENT_ID` (既定 `fastapi-app`) | `KEYCLOAK_CP_CLIENT_ID` (既定 `fastapi-cp`) |
| ログイン時の追加検証 | トークンの `tenant_id` = レジストリの `tenant_id`、テナントが ACTIVE | `saas_admin` / `saas_viewer` のいずれかを持つ |
| ログイン後の遷移先 | `/{tenant_code}/` | `/cp/` |
| ログアウト後の遷移先 | `/{tenant_code}/login` | `/cp/login` |
| コールバック失敗時の遷移先 | `/{tenant_code}/login?error=<code>` (テナント不明は `/?error=<code>`) | `/cp/login?error=<code>` |

- Cookie は `HttpOnly`、`SameSite=Lax`、`Secure` は `APP_ENV` から導出。値は `itsdangerous` でプレーン毎の salt を使って署名する
- クライアントシークレットは `KC_CLIENT_SECRET_SEED` から導出する (`modules.keycloak_admin.derive_client_secret`)。保存しない
- id_token (署名・`aud`・`iss`・`nonce`) と access token (署名・`iss`・`azp`) を JWKS で検証する。ロールは access token の `realm_access.roles` から、プレーンの許可リストにあるものだけを載せる

### 認証フロー シーケンス (AP)

```
Browser          React (5173)       FastAPI (8000)       KeyCloak (8080)
  |                  |                    |                     |
  |  GET /alpha/login|                    |                     |
  |----------------->| (window.location)  |                     |
  |                  | GET /api/auth/app/login?tenant_code=alpha |
  |                  |------------------->|                     |
  |                  |    レジストリで tenant-alpha に解決          |
  |                  |    state/PKCE/nonce を Redis に保存          |
  |                  |       302 redirect to KC /auth?state=xxx  |
  |<----------------------------------------------------|       |
  |  GET /keycloak/realms/tenant-alpha/.../auth          |       |
  |------------------------------------------------------------->|
  |  ユーザー認証                                                  |
  |  302 redirect to APP_CALLBACK_URL?code=xxx&state=xxx         |
  |<-------------------------------------------------------------|
  |  GET /api/auth/callback?code=xxx&state=xxx                   |
  |----------------->|------------------->|                     |
  |                  |    state 取り出し (1 回限り)                |
  |                  |    レジストリで ACTIVE を再確認               |
  |                  |    POST /token (内部URL, 導出シークレット)     |
  |                  |    ----------------------------------->   |
  |                  |    ← access_token, id_token, refresh_token |
  |                  |    JWKS で検証、tenant_id を照合             |
  |                  |    Redis session:app:{sid} に保存           |
  |                  |    302 /alpha/ + Set-Cookie rf_sid_app     |
  |<----------------------------------------------------|       |
  |  GET /api/auth/app/status (with Cookie)                      |
  |----------------->|------------------->|                     |
  |                  |<------- {authenticated, plane, tenant_code, user} |
```

### URL の使い分け

| 用途 | 使用する URL | 環境変数 |
|---|---|---|
| ブラウザへの KeyCloak リダイレクト | `KEYCLOAK_EXTERNAL_URL` (例: `http://localhost:8080`) | `KEYCLOAK_EXTERNAL_URL` |
| サーバー間トークン交換 / JWKS 取得 | Docker 内部 URL (例: `http://keycloak_c:8080`) | `KEYCLOAK_URL` |
| ログイン後のフロントエンドリダイレクト | `FRONTEND_URL` (例: `http://localhost:5173`) | `FRONTEND_URL` |

### 依存関係

他エンドポイントで認証を要求する場合は `modules.auth` の依存関数を使用する:

```python
from fastapi import APIRouter, Depends
from modules.auth import get_current_app_user, require_cp_roles, require_csrf_protection

router = APIRouter(dependencies=[Depends(require_csrf_protection)])  # 変更系の CSRF 対策

@router.get("/me")
def me(user: dict = Depends(get_current_app_user)):
    return {"user": user}

@router.post("/cp/tenants")
def create_tenant(user: dict = Depends(require_cp_roles("saas_admin"))):
    ...
```

`get_current_user` は移行期間中の別名 (= `get_current_app_user`)。
