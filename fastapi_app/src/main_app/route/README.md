# main_app/route

FastAPI アプリケーションのルーティング定義をサブパッケージとして管理するディレクトリ。

各サブパッケージがルーターを定義し、`app.py` で `include_router` によって登録される。

---

## ディレクトリ構成

```
route/
└── auth/
    ├── __init__.py  # router を公開
    └── apiapp.py    # OIDC 認証エンドポイントの実装
```

---

## auth — KeyCloak 認証ルーター

**prefix**: `/api/auth`

KeyCloak との OIDC Authorization Code Flow を実装する BFF エンドポイント群。

React は Vite proxy 経由で全て `http://localhost:5173/api/auth/...` にアクセスし、  
FastAPI がブラウザの代わりに KeyCloak と通信する。

### エンドポイント一覧

| メソッド | パス | 概要 |
|---|---|---|
| `GET` | `/api/auth/login` | 認可リクエストを開始する |
| `GET` | `/api/auth/callback` | 認可コードをトークンに交換してセッションを確立する |
| `GET` | `/api/auth/status` | セッションを検証してユーザー情報を返す |
| `POST` | `/api/auth/logout` | セッションを削除してログアウトする |

> 全エンドポイントは `include_in_schema=False` のため OpenAPI ドキュメントには表示されない。

---

### 認証フロー シーケンス

```
Browser          React (5173)       FastAPI (8000)       KeyCloak (8080)
  |                  |                    |                     |
  |  GET /login      |                    |                     |
  |----------------->| (window.location)  |                     |
  |                  | GET /api/auth/login?realm=tenant-a        |
  |                  |------------------->|                     |
  |                  |       302 redirect to KC /auth?state=xxx  |
  |<----------------------------------------------------|       |
  |  GET /keycloak/realms/tenant-a/.../auth              |       |
  |------------------------------------------------------------->|
  |                                                              |
  |                  KeyCloak ログイン UI 表示                    |
  |  ユーザー認証                                                  |
  |------------------------------------------------------------->|
  |  302 redirect to APP_CALLBACK_URL?code=xxx&state=xxx         |
  |<-------------------------------------------------------------|
  |  GET /api/auth/callback?code=xxx&state=xxx                   |
  |----------------->|                    |                     |
  |                  |------------------->|                     |
  |                  |    state 検証 (Redis)                      |
  |                  |    POST /token (内部URL, S2S)              |
  |                  |    ----------------------------------->   |
  |                  |    ← access_token, id_token               |
  |                  |    id_token JWT をデコードしてユーザー情報取得  |
  |                  |    Redis にセッション保存                    |
  |                  |    302 redirect /button + Set-Cookie       |
  |<----------------------------------------------------|       |
  |                                                              |
  |  GET /api/auth/status (with Cookie)                          |
  |----------------->|------------------->|                     |
  |                  |    Cookie 検証 + Redis セッション確認        |
  |                  |<------- {authenticated: true, user: ...}  |
```

---

### URL の使い分け

| 用途 | 使用する URL | 環境変数 |
|---|---|---|
| ブラウザへの KeyCloak リダイレクト | `KEYCLOAK_EXTERNAL_URL` (例: `http://localhost:8080`) | `KEYCLOAK_EXTERNAL_URL` |
| サーバー間トークン交換 / userinfo フォールバック | Docker 内部 URL (例: `http://keycloak_c:8080`) | `KEYCLOAK_URL` |
| ログイン後のフロントエンドリダイレクト | `FRONTEND_URL` (例: `http://localhost:5173`) | `FRONTEND_URL` |

---

### ユーザー情報取得の戦略

1. KeyCloak のトークンレスポンスに `id_token` が含まれる場合は JWT をデコードしてユーザー情報を取得する  
   → KeyCloak 内部 URL / 外部 URL の issuer ミスマッチ問題を回避できる
2. `id_token` が存在しない、または JWT 形式が不正な場合は `/userinfo` エンドポイントにフォールバックする

---

### セッション管理

- セッションデータは Redis に保存 (`session:{session_id}` キー)
- クライアントには HMAC 署名済みのセッション ID のみを HttpOnly Cookie (`rf_sid`) で渡す
- 署名の検証には `itsdangerous.URLSafeSerializer` を使用し、Cookie の改ざんを検知する

---

### 依存関係

他エンドポイントで認証を要求する場合は `modules.auth.get_current_user` Dependency を使用する:

```python
from modules.auth import get_current_user
from fastapi import Depends

@router.get("/protected")
def protected(user: dict = Depends(get_current_user)):
    return {"user": user}
```
