# KeyCloakセットアップ手順 (開発環境)

この手順は、以下の実装前提に対応しています。

- 認証フロー: Authorization Code Flow (OIDC)
- FastAPIがBFFとして動作
- Reactは `http://localhost:5173`、FastAPIは `http://localhost:8000`
- KeyCloakは `http://localhost:8080/keycloak`
- マルチテナント方式: Realm per tenant

## 1. 事前確認

1. `docker-compose.yaml` の `keycloak_c` が起動していることを確認する。
2. 管理画面にアクセスする。
   - URL: `http://localhost:8080/keycloak`
3. 管理者でログインする。
   - ユーザー名: `KC_BOOTSTRAP_ADMIN_USERNAME`
   - パスワード: `KC_BOOTSTRAP_ADMIN_PASSWORD`

## 2. 自動化スクリプトで作成する方法

手動手順の代わりに、以下のスクリプトで Realm / Client / User を一括作成できる。

- スクリプト: `./setup_realm_client_user.sh`

引数:

1. `realm_name` (作成するRealm名)
2. `client_id` (作成するClient ID)
3. `username` (作成するユーザー名)
4. `user_password` (任意。省略時は `KEYCLOAK_INIT_USER_PASSWORD` または `ChangeMe123!`)

実行例:

```bash
bash keycloak_c/setup_realm_client_user.sh tenant-a fastapi-app user001 ChangeMe123!
```

管理者接続情報を環境変数で指定する例:

```bash
KEYCLOAK_BASE_URL=http://localhost:8080 \
KEYCLOAK_HTTP_RELATIVE_PATH=keycloak \
KEYCLOAK_ADMIN_USERNAME=admin \
KEYCLOAK_ADMIN_PASSWORD=admin \
APP_CALLBACK_URL=http://localhost:5173/api/auth/callback \
APP_POST_LOGOUT_REDIRECT_URI=http://localhost:5173/* \
APP_WEB_ORIGIN=http://localhost:5173 \
bash keycloak_c/setup_realm_client_user.sh tenant-a fastapi-app user001
```

スクリプト実行後、標準出力に `KEYCLOAK_CLIENT_SECRET` が表示されるため、`.env` に設定する。

`.env` を更新したら、**`docker compose restart` ではなく `docker compose up -d` で入れ直す**こと。
`restart` は既存コンテナを再起動するだけで `.env` を読み直さないため、古い値のまま起動する。

```bash
docker compose up -d fastapi_app
```

反映できたかは、FastAPI の起動ログで判定できる。既定値のままだと次の警告が出る。

```text
WARNING: 開発用の既定値のままの環境変数があります: KEYCLOAK_CLIENT_SECRET, SESSION_SECRET_KEY
```

なお `.env` はリポジトリ**ルート**のものを compose が読む。`react_app/.env` は Vite 用であり別物なので注意する。

## 3. テナント用Realm作成

各テナントごとにRealmを作成する。

1. 左上のRealmセレクタから `Create realm` を選択。
2. Realm name にテナント名を入力。
   - 例: `tenant-a`, `tenant-b`
3. `Create` を押下。

運用メモ:

- Realm per tenantでは、ユーザー名の一意性は通常「Realm内」で保証される。
- 要件「ユーザーIDはシステムユニーク」を満たすため、全Realm共通で同じ命名規則を使うこと。
  - 例: `global-user-id` をそのまま username に採用
  - 例: メールアドレスを username として統一

## 4. クライアント作成 (各Realmで実施)

各Realmで同じクライアントを作成する。

1. 対象Realmを開く。
2. `Clients` -> `Create client`。
3. 次を入力して `Next`。
   - Client type: `OpenID Connect`
   - Client ID: `fastapi-app` (環境変数 `KEYCLOAK_CLIENT_ID` と一致させる)
4. Capability config:
   - Client authentication: `On` (confidential client)
   - Authorization: `Off`
   - Standard flow: `On`
   - Direct access grants: `Off`
5. `Save`。

## 5. Redirect URI / Logout URI 設定 (各Realm)

作成した client (`fastapi-app`) の `Settings` で設定する。

1. Valid redirect URIs:
   - `http://localhost:5173/api/auth/callback`
2. Valid post logout redirect URIs:
   - `http://localhost:5173/*`
3. Web origins:
   - `http://localhost:5173`
4. `Save`。

## 6. Client Secret の取得

1. client (`fastapi-app`) の `Credentials` タブを開く。
2. `Client secret` を確認。
3. 取得した値を `.env` の `KEYCLOAK_CLIENT_SECRET` に設定する。

関連する `.env` 例:

```env
KEYCLOAK_CLIENT_ID=fastapi-app
KEYCLOAK_CLIENT_SECRET=<your-client-secret>
KEYCLOAK_EXTERNAL_URL=http://localhost:8080
KEYCLOAK_HTTP_RELATIVE_PATH=keycloak
APP_CALLBACK_URL=http://localhost:5173/api/auth/callback
FRONTEND_URL=http://localhost:5173
```

## 7. ユーザー作成 (各Realm)

1. 対象Realmを開く。
2. `Users` -> `Add user`。
3. 必須情報を入力して作成。
   - Username: システム全体で重複しないID
   - Email: 任意
   - Email verified: 必要に応じて `On`
   - Enabled: `On`
4. 作成後、`Credentials` タブでパスワード設定。
   - `Temporary` は開発中は `Off` 推奨
   - `Set password`

## 8. ログイン動作確認

1. Reactアプリにアクセス: `http://localhost:5173/login`
2. Realm名を入力してログインボタン押下。
   - 例: `tenant-a`
3. KeyCloakログイン画面に遷移することを確認。
4. 作成したユーザーでログイン。
5. ログイン成功後、`/button` へ遷移することを確認。

## 9. トラブルシュート

### A. `Invalid parameter: redirect_uri`

- Realm内clientの `Valid redirect URIs` を確認。
- `http://localhost:5173/api/auth/callback` が完全一致で登録されているか確認。

### B. `unauthorized_client` / `Client authentication failed`

- `.env` の `KEYCLOAK_CLIENT_SECRET` が正しいか確認。
- 対象Realmの client ID が `fastapi-app` になっているか確認。

### C. ログイン後に未認証になる

- ブラウザで Cookie が保存されているか確認。
- Vite proxy (`/api` -> FastAPI) が有効か確認。
- `REDIS_URL` と `SESSION_SECRET_KEY` が設定されているか確認。

### D. 作成したはずの Realm が消えている

KeyCloak のデータ保存先 (`keycloak_c` のボリューム) が**ブランチによって異なる**場合がある。
ブランチを切り替えてから `docker compose up -d` すると、別のデータディレクトリを参照する
コンテナが作り直され、以前作成した Realm が見えなくなることがある。

確認方法:

```bash
docker inspect rf_stack-keycloak_c-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

Realm 一覧は管理 API でも確認できる。

```bash
TOKEN=$(curl -s http://localhost:8080/keycloak/realms/master/protocol/openid-connect/token \
  -d grant_type=password -d client_id=admin-cli -d username=admin -d password=admin \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/keycloak/admin/realms \
  | python3 -c 'import json,sys; print([r["realm"] for r in json.load(sys.stdin)])'
```

消えていた場合は `setup_realm_client_user.sh` を再実行する。**client secret は再発行される**ため、
`.env` の `KEYCLOAK_CLIENT_SECRET` も必ず更新すること。

### E. ログアウトしても KeyCloak のセッションが残る / `Invalid token issuer`

KeyCloak はトークンの `iss` とアクセスされた URL の一致を検証する。本構成では
**ブラウザが外部 URL (`http://localhost:8080`) で認可する**ため、発行されるトークンの
`iss` は外部 URL になる。

このため、サーバーから**内部 URL (`http://keycloak_c:8080`) にログアウトを要求すると失敗する**。

```json
{"error":"invalid_grant","error_description":"Invalid token issuer. Expected 'http://keycloak_c:8080/keycloak/realms/tenant-a'"}
```

このため `docker-compose.yaml` では **`KC_HOSTNAME` を設定して issuer を固定**している。

```yaml
KC_HOSTNAME: ${KC_HOSTNAME-http://localhost:8080/keycloak}
```

これがないと、access token のリフレッシュ (`grant_type=refresh_token`) も同じ理由で
失敗する。**`KC_HTTP_RELATIVE_PATH` のパスまで含めて指定する**こと。パスを省くと
issuer から `/keycloak` が欠落し、ブラウザからのアクセスと食い違う。

issuer は discovery で確認できる。

```bash
curl -s http://localhost:8080/keycloak/realms/tenant-a/.well-known/openid-configuration \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["issuer"])'
# → http://localhost:8080/keycloak/realms/tenant-a
```

なおログアウト自体は**フロントチャネル (RP-Initiated Logout)** で行っている。
`POST /api/auth/logout` はリダイレクトではなく遷移先 URL を JSON で返すので、
呼び出し側 (SPA) が `window.location.href` でトップレベル遷移する必要がある。
`fetch` のままではブラウザ側の KeyCloak セッション Cookie が消えない。

確認方法 — ログアウト前後で SSO セッション数が減ることを見る。

```bash
CID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/keycloak/admin/realms/tenant-a/clients?clientId=fastapi-app" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/keycloak/admin/realms/tenant-a/clients/$CID/user-sessions" \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)), "件")'
```

## 10. テナント追加時の最小作業

新規テナント追加時は、以下のみ実施すればよい。

1. 新しいRealm作成
2. `fastapi-app` client作成
3. Redirect URI / Web origins設定
4. ユーザー作成
5. Realm名でログイン確認
