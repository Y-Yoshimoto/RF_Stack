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
| `realms.py` / `clients.py` / `roles.py` / `users.py` | 冪等な `ensure_*` 関数（無ければ作成、あれば取得。作成時の 409 は既存扱い）。`set_realm_enabled` / `delete_realm_if_exists` も `realms.py` |
| `templates.py` | レルムのテンプレート（テナントレルム・`control-plane`）、ユーザー、停止・削除、払い出し用の管理クライアント。**払い出しサービスとシードはここの関数だけを使う** |
| `provisioning.py` | 旧シェルスクリプト相当の手順（CLI 用） |
| `cli.py` | 開発用の単発セットアップ |
| `errors.py` | `KeycloakAdminError` と `Auth` / `Timeout` / `Connection` の派生 |

## 2. 開発用にレルムを作る（CLI）

`fastapi_app` コンテナ内で実行する（コンテナ内外の判定は `run-checks` スキル）。

```bash
make d-run SERVICE=fastapi_app CMD="uv run python -m modules.keycloak_admin.cli <realm_name> <client_id> <username> [password]"
```

- 例: `... cli tenant-alpha fastapi-app alpha-admin`
- クライアントシークレットは `KC_CLIENT_SECRET_SEED` から導出した値（`modules.keycloak_admin.derive_client_secret`、02 §3.3）を設定する。BFF も同じ式で導出するため `.env` への転記は不要。最後に表示される `KEYCLOAK_CLIENT_SECRET=...` は確認用
- ユーザーにはメール・姓・名を必ず設定する（`--email` / `--first-name` / `--last-name`、省略時は `{username}@example.com` / `{username}` / `User`）。既存ユーザーは空の項目だけを補う
- 何度実行しても同じ結果になる。既存クライアントの設定は毎回反映し、ユーザーのパスワードは毎回上書きする
- `-v` で Admin API の呼び出しを標準エラーに出す（トークン・パスワードは出ない）
- 環境変数（`KEYCLOAK_URL`、`KEYCLOAK_ADMIN_USERNAME` / `KEYCLOAK_ADMIN_PASSWORD` 等）は `keycloak_c/KEYCLOAK_SETUP.md` §2 の表を参照する

**注意**: Keycloak の既定のユーザープロフィールはメール・姓・名が必須のため、欠けたユーザーは開発用ログイン（パスワードグラント）が `invalid_grant: Account is not fully set up` で失敗する。コードからは `UserSpec` に `email` / `first_name` / `last_name` を渡して作成する（既存ユーザーを救済する場合は `ensure_user(..., fill_missing_profile=True)`）。

**注意**: CLI で作ったレルムはテナントレジストリに登録されず `tenant_id` クレームも無いため、通常のログイン（`/api/auth/app/login?tenant_code=`）は通らない。開発用ログイン（`run-checks` スキル）で確認する。

## 3. 払い出し処理を実装する

### 3.1 守ること

1. **各ステップは冪等にする。** `ensure_*` を使い、再実行で同じ状態に収束させる。削除も「既に無ければスキップ」にする。
2. **`PROVISIONING` の記録は Keycloak を呼ぶ前に別トランザクションでコミットする。** 以降の各ステップの結果も払い出し履歴に都度コミットする。
3. **全体の締め切りを守る。** `KeycloakAdminClient` の `deadline_seconds` を使い、同期 API が 30 秒以内に返るようにする。
4. **一時パスワードをどこにも残さない。** レスポンスで一度だけ返し、ログ・監査ログ・払い出し履歴のエラー情報に含めない。`KeycloakAdminError` の detail をそのまま保存しない。
5. **権限を分ける。** CP の払い出しは `cp-provisioner`（master、`create-realm`）、AP のユーザー管理は各テナントレルムの `tenant-user-admin`（`realm-management` の `manage-users` / `view-users` / `query-users` のみ）。AP から `cp-provisioner` を使わない。
6. **クライアントシークレットは保存しない。** `KC_CLIENT_SECRET_SEED` から HMAC で導出した値を設定する（02 §3.3）。

### 3.2 テンプレートと関数の対応（02 §3.1 / §3.2）

`modules.keycloak_admin.templates` の関数を使う。いずれも冪等で、再実行すると同じ状態に収束する。

| 用途 | 関数 |
| --- | --- |
| 管理クライアントの生成 | `create_provisioner_admin_client()`。開発（`APP_ENV=development`）は master / `admin-cli` のパスワードグラント、それ以外は `cp-provisioner` のクライアントクレデンシャル（`KEYCLOAK_PROVISIONER_CLIENT_ID` / `KEYCLOAK_PROVISIONER_CLIENT_SECRET`）。締め切り 30 秒は生成時点から数えるため、**1 テナントの払い出しごとに `with` で作る** |
| テナントレルム一式 | `ensure_tenant_realm(admin, *, tenant_code, tenant_id, display_name, enabled=True) -> TenantRealmResult`（`realm_name` を含む。シークレットは含まない） |
| `control-plane` レルム一式 | `ensure_control_plane_realm(admin) -> ControlPlaneRealmResult` |
| ユーザー（初期管理者・シード） | `ensure_tenant_user(admin, *, realm_name, username, email, first_name, last_name, roles, password, temporary) -> user_id` |
| 停止・再開 | `set_realm_enabled(admin, realm_name, enabled)` |
| 物理削除 | `delete_realm_if_exists(admin, realm_name) -> bool`（`master` は拒否） |

`ensure_tenant_realm` が作るもの:

| 項目 | 内容 | 部品 |
| --- | --- | --- |
| レルム `tenant-{tenant_code}` | 表示名、`duplicateEmailsAllowed=false`、`loginWithEmailAllowed=true`、登録・パスワードリセット無効、`bruteForceProtected=true`、`enabled`（既存レルムにも毎回反映） | `ensure_realm(admin, RealmSpec(...))` |
| レルムロール | `tenant_admin` / `member`。既定ロール（`default-roles-*`）に `member` | `ensure_realm_role` / `ensure_default_realm_roles` |
| ログイン用クライアント（`KEYCLOAK_CLIENT_ID`、既定 `fastapi-app`） | confidential、Standard Flow + PKCE(S256)、Implicit 無効、導出シークレット、リダイレクト URI `APP_CALLBACK_URL`、ログアウト後 `{FRONTEND_URL}/{tenant_code}/*`。`directAccessGrants` は `APP_ENV=development` のときだけ | `ensure_client` |
| マッパー | `tenant_id` のハードコードクレーム（ID / アクセストークン・userinfo）、Audience（`aud` にログイン用クライアント）。既存の `tenant_id` マッパーが別の値なら上書きせずエラー | `ensure_protocol_mapper` + `hardcoded_claim_mapper` / `audience_mapper` |
| サービスアカウント `tenant-user-admin` | サービスアカウントのみ、導出シークレット。`realm-management` の `manage-users` / `view-users` / `query-users` | `ensure_client` + `get_service_account_user_id` + `ensure_user_client_roles` |

`ensure_tenant_user` の挙動:

- メール（確認済み）・姓・名は必須。既存ユーザーは**空の項目だけ**埋める
- パスワードは**既存ユーザーでも毎回設定し直す**（払い出しの再実行で返す一時パスワード、シードの開発用パスワードを有効にするため）。`temporary=True` なら必須アクション `UPDATE_PASSWORD`
- ロールは不足分だけ追加する（余分は外さない）

開発用シードの認証情報は `fastapi_app/src/modules/auth/dev_profiles.py`（`DEV_TENANTS` / `DEV_TENANT_USERS` / `DEV_CP_USERS` / `DEV_USERS`）に 1 箇所で定義し、開発用ログインのプロファイル（`DEV_PROFILES`）と共有する。

**AP から `tenant-user-admin` でロールを付与する場合**: `tenant-user-admin` は `GET /roles/{name}`（`view-realm` が必要）を呼べないため、`ensure_user_realm_roles` は使えない。ロールの ID は `GET /users/{id}/role-mappings/realm/available` から取得して `POST /users/{id}/role-mappings/realm` する。付与できるロールは `tenant_admin` / `member` に限定する（`realm-management` のロールをテナントユーザーに付与させない）。
この手順は `modules/keycloak_admin/tenant_users.py`（`create_user` / `set_user_realm_roles` / `set_user_enabled` / `logout_user` / `update_user_names` / `delete_user_if_exists`）に実装済みで、管理クライアントは `templates.create_tenant_user_admin_client(realm_name)` で作る（1 操作ごとに `with`）。AP のユーザー管理は `main_app/services/user_service.py` の `UserService` から使う（tenant-isolation スキル §4.1）。`create_user` は冪等にしない（既存のユーザー名・メールは 409。`ensure_user` は既存ユーザーを採用してパスワードを上書きするため AP からは使わない）。

### 3.3 テスト

- HTTP は `httpx.Client(transport=httpx.MockTransport(handler))` を `KeycloakAdminClient(..., http_client=...)` に渡して差し替える。トークンエンドポイントも同じ handler で応答できる
- 時間に依存する処理（締め切り・トークンのキャッシュ）は `clock` を注入する
- `ensure_*` は「無い → 作成」「ある」「作成時 409」の 3 分岐を必ず確認する
- 実機の Keycloak に対する確認でレルムを作った場合は、確認後に削除する（`tenant-porttest` のような使い捨ての名前を使う）

### 3.4 払い出しサービス（CP）を使う

テナントのライフサイクル操作は `control_plane_app.services.tenant_provisioning.TenantProvisioningService` に集約している（3.1 の守ることは実装済み）。API・定期ジョブ・開発用シードはいずれもこれを呼び、Keycloak や `t_tenant` を直接操作する別経路を作らない。

```python
from modules.keycloak_admin.templates import create_provisioner_admin_client
from control_plane_app.services.tenant_provisioning import InitialAdminSpec, TenantProvisioningService

with create_provisioner_admin_client() as admin:          # 1 操作ごとに作る（締め切り 30 秒）
    service = TenantProvisioningService(session, admin)  # session は CP DB（cp_runtime）。コミットはサービスが行う
    result = service.onboard(tenant_code="acme", name="Acme", initial_admin=InitialAdminSpec(email="admin@acme.example"),
                             actor=user["sub"], request_id=request_id)
# result.temporary_password はレスポンスで一度だけ返す（ログ・DB に残さない）
```

| メソッド | 遷移（01 §6.1） | 備考 |
| --- | --- | --- |
| `onboard(tenant_code, name, initial_admin, actor)` | → PROVISIONING → ACTIVE / FAILED | 形式・予約語（`modules/tenancy/tenant_code.py`）を検証。失敗時は FAILED をコミットして `ProvisioningFailedError` |
| `retry(tenant_id, initial_admin, actor, expected_version=None)` | FAILED / 中断した PROVISIONING → ACTIVE / FAILED | 初期管理者は台帳に無いため再指定する。一時パスワードは新しく発行され、前回の値は無効になる |
| `suspend` / `resume` / `request_deletion(tenant_id, actor, expected_version=None)` | ACTIVE ⇄ SUSPENDED、ACTIVE / SUSPENDED / FAILED → PENDING_DELETION | 行ロックの下でレルムを切り替えてから状態を更新する。Keycloak が失敗したら状態は変えない（`TenantRealmOperationError`） |
| `deprovision(tenant_id)` | PENDING_DELETION（30 日経過）/ DEPROVISIONING → DELETED | 定期ジョブ専用。AP データ削除 → レルム削除。失敗時は DEPROVISIONING のまま |

- 例外と HTTP ステータス（422 / 404 / 409 / 412 / 502）の対応は `control_plane_app/services/errors.py` の docstring を正とする。API は `If-Match` の値を `expected_version` に渡す
- 同じテナントの払い出し・再実行・物理削除は CP DB の advisory lock（`cp:tenant:{tenant_code}`）で排他する。取れなければ `TenantOperationInProgressError`（409）
- `actor` は CP 管理者の IdP subject、定期ジョブ・シードは `system`。各操作で CP 監査ログ（`tenant.create` / `tenant.provision_succeed` / `tenant.provision_fail` / `tenant.provision_retry` / `tenant.provision_reap` / `tenant.suspend` / `tenant.resume` / `tenant.request_deletion` / `tenant.deprovision_start` / `tenant.deprovision_fail` / `tenant.delete`）を書く
- 払い出し履歴の `error` と監査ログには `step=...; error=<例外の型>; http_status=...` だけを残す
- 定期ジョブ: `control_plane_app.jobs.provisioning_reaper.run_provisioning_reaper()`（10 分以上 PROVISIONING → FAILED）、`control_plane_app.jobs.tenant_purge.run_tenant_purge()`（猶予経過テナントの物理削除）。CLI は `uv run python -m control_plane_app.jobs <provisioning_reaper|tenant_purge>`
- テーマが AP にテナントスコープのテーブルを追加したら、物理削除の対象を `control_plane_app/repositories/app_tenant_data.py` の `TENANT_DATA_PURGE_TABLES` に削除順（子テーブルが先）で追加する（01 §13 #9）
- 開発用シード: `make d-run SERVICE=fastapi_app CMD="uv run python -m control_plane_app.seed"`（冪等、`APP_ENV=development` が明示されている場合のみ。02 §7.1）
