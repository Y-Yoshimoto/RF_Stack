---
name: tenant-provisioning
description: Keycloak のレルム・クライアント・ロール・マッパー・ユーザーを冪等に作成する手順と、テナント払い出し処理の実装規則。Python の modules.keycloak_admin（Admin API クライアントと ensure 系関数、CLI）の使い方を扱う。「開発用のレルムを作って」「Keycloak にユーザーを追加したい」「クライアントシークレットを取り直したい」「テナントの払い出し処理を実装して」「レルムのテンプレートを変えたい」といった依頼で使用する。
---

# テナント払い出しと Keycloak のセットアップ

仕様の正は `docs/architecture/01-platform-concepts.md`（§6 ライフサイクル、§7 認証・認可）と `docs/architecture/02-platform-implementation.md`（§3 Keycloak）。
Keycloak の画面操作による手動手順は `keycloak_c/KEYCLOAK_SETUP.md` を参照する。

## 1. 部品

`fastapi_app/src/modules/keycloak_admin/`（httpx の同期クライアント。FastAPI に依存しない）

| モジュール | 役割 |
| --- | --- |
| `admin_client.py` | `KeycloakAdminClient`。全体の締め切り（既定 30 秒）と 1 リクエストのタイムアウト（既定 10 秒）、401 時に 1 回だけ再試行 |
| `token_provider.py` | 管理トークンの取得。`PasswordGrantTokenProvider`（master / admin-cli、開発用）、`ClientCredentialsTokenProvider`（`cp-provisioner` / `tenant-user-admin` 用） |
| `realms.py` / `clients.py` / `roles.py` / `users.py` | 冪等な `ensure_*` 関数（無ければ作成、あれば取得。作成時の 409 は既存扱い） |
| `provisioning.py` | 複数の `ensure_*` を組み合わせた手順。テナントレルムのテンプレートはここに手順関数として追加する |
| `cli.py` | 開発用の単発セットアップ |
| `errors.py` | `KeycloakAdminError` と `Auth` / `Timeout` / `Connection` の派生 |

## 2. 開発用にレルムを作る（CLI）

`fastapi_app` コンテナ内で実行する（コンテナ内外の判定は `run-checks` スキル）。

```bash
make d-run SERVICE=fastapi_app CMD="uv run python -m modules.keycloak_admin.cli <realm_name> <client_id> <username> [password]"
```

- 例: `... cli tenant-alpha fastapi-app alpha-admin`
- 最後に `KEYCLOAK_CLIENT_SECRET=...` が表示される。現行の単一クライアント構成ではこれを `.env` に設定し、`docker compose up -d fastapi_app` で反映する（`restart` では `.env` を読み直さない）
- 何度実行しても同じ結果になる。既存クライアントの設定は毎回反映し、ユーザーのパスワードは毎回上書きする
- `-v` で Admin API の呼び出しを標準エラーに出す（トークン・パスワードは出ない）
- 環境変数（`KEYCLOAK_URL`、`KEYCLOAK_ADMIN_USERNAME` / `KEYCLOAK_ADMIN_PASSWORD` 等）は `keycloak_c/KEYCLOAK_SETUP.md` §2 の表を参照する

**注意**: CLI はユーザー名だけでユーザーを作る。Keycloak の既定のユーザープロフィールはメール・姓・名が必須のため、そのままでは開発用ログイン（パスワードグラント）が `invalid_grant: Account is not fully set up` で失敗する。コードからは `UserSpec` に `email` / `first_name` / `last_name` を渡して作成する。

## 3. 払い出し処理を実装する

### 3.1 守ること

1. **各ステップは冪等にする。** `ensure_*` を使い、再実行で同じ状態に収束させる。削除も「既に無ければスキップ」にする。
2. **`PROVISIONING` の記録は Keycloak を呼ぶ前に別トランザクションでコミットする。** 以降の各ステップの結果も払い出し履歴に都度コミットする。
3. **全体の締め切りを守る。** `KeycloakAdminClient` の `deadline_seconds` を使い、同期 API が 30 秒以内に返るようにする。
4. **一時パスワードをどこにも残さない。** レスポンスで一度だけ返し、ログ・監査ログ・払い出し履歴のエラー情報に含めない。`KeycloakAdminError` の detail をそのまま保存しない。
5. **権限を分ける。** CP の払い出しは `cp-provisioner`（master、`create-realm`）、AP のユーザー管理は各テナントレルムの `tenant-user-admin`（`manage-users` のみ）。AP から `cp-provisioner` を使わない。
6. **クライアントシークレットは保存しない。** `KC_CLIENT_SECRET_SEED` から HMAC で導出した値を設定する（02 §3.3）。

### 3.2 テナントレルムのテンプレート（02 §3.2）

| 手順 | 使う関数 |
| --- | --- |
| レルム `tenant-{tenant_code}`（`duplicateEmailsAllowed=false`、`bruteForceProtected=true`、登録・パスワードリセット無効） | `ensure_realm(admin, RealmSpec(...))` |
| レルムロール `tenant_admin` / `member` | `ensure_realm_role` |
| ログイン用クライアント `fastapi-app`（confidential、PKCE、導出したシークレット。`directAccessGrants` は開発のみ） | `ensure_client` |
| マッパー: `tenant_id` のハードコードクレーム、Audience | `ensure_protocol_mapper` + `hardcoded_claim_mapper` / `audience_mapper` |
| サービスアカウント `tenant-user-admin` | `ensure_client`（サービスアカウントのみ） + `realm-management` ロールの付与（未実装。追加が必要） |
| 初期管理者（メール・姓・名あり、一時パスワード、`UPDATE_PASSWORD`） | `ensure_user` + `set_user_password(..., temporary=True)` |

### 3.3 テスト

- HTTP は `httpx.Client(transport=httpx.MockTransport(handler))` を `KeycloakAdminClient(..., http_client=...)` に渡して差し替える。トークンエンドポイントも同じ handler で応答できる
- 時間に依存する処理（締め切り・トークンのキャッシュ）は `clock` を注入する
- `ensure_*` は「無い → 作成」「ある」「作成時 409」の 3 分岐を必ず確認する
- 実機の Keycloak に対する確認でレルムを作った場合は、確認後に削除する（`tenant-porttest` のような使い捨ての名前を使う）
