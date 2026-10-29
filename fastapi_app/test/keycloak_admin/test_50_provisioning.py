# -*- coding: utf-8 -*-
"""provisioning(旧シェルスクリプト相当の setup_realm_client_user と build_app_client_spec)のテスト。"""
import httpx
import pytest
import pytest_check as check

from modules.keycloak_admin import AppClientSettings, KeycloakAdminAuthError, KeycloakAdminError, build_app_client_spec, setup_realm_client_user

R = "/keycloak/admin/realms"
REALM = f"{R}/tenant-a"
CLIENTS = f"{REALM}/clients"
USERS = f"{REALM}/users"
SECRET = "client-secret-VALUE"
PASSWORD = "Pw-for-user-1!"


def _spec():
    return build_app_client_spec("fastapi-app", AppClientSettings(callback_url="http://app/cb", post_logout_redirect_uri="http://app/*", web_origin="http://app"))


def _fresh_environment(kc):
    """何も無い状態の Keycloak を登録する。"""
    kc.on("GET", REALM, status=404)
    kc.on("POST", R, status=201)
    kc.on("GET", CLIENTS, json=[])
    kc.on("POST", CLIENTS, httpx.Response(201, headers={"Location": f"http://kc{CLIENTS}/cid-1"}))
    kc.on("GET", f"{CLIENTS}/cid-1/client-secret", json={"value": SECRET})
    kc.on("GET", USERS, json=[])
    kc.on("POST", USERS, httpx.Response(201, headers={"Location": f"http://kc{USERS}/uid-1"}))
    kc.on("PUT", f"{USERS}/uid-1/reset-password", status=204)


def _existing_environment(kc):
    """すべて作成済みの状態を登録する。"""
    kc.on("GET", REALM, json={"realm": "tenant-a"})
    kc.on("GET", CLIENTS, json=[{"id": "cid-1", "clientId": "fastapi-app"}])
    kc.on("PUT", f"{CLIENTS}/cid-1", status=204)
    kc.on("GET", f"{CLIENTS}/cid-1/client-secret", json={"value": SECRET})
    kc.on("GET", USERS, json=[{"id": "uid-1", "username": "alice"}])
    kc.on("PUT", f"{USERS}/uid-1/reset-password", status=204)


def _run(kc, messages=None):
    return setup_realm_client_user(kc.admin, realm="tenant-a", client_spec=_spec(), username="alice", password=PASSWORD, report=(messages.append if messages is not None else (lambda _m: None)))


class TestBuildAppClientSpec:
    """build_app_client_spec。"""

    def test_matches_legacy_script(self):
        """旧シェルスクリプトと同じ: confidential・認可コード + パスワードグラント・サービスアカウント無効、URL は設定から。"""
        spec = _spec()
        check.equal(spec.client_id, "fastapi-app")
        check.equal((spec.redirect_uris, spec.web_origins, spec.post_logout_redirect_uris), (("http://app/cb",), ("http://app",), ("http://app/*",)))
        check.equal((spec.public_client, spec.standard_flow_enabled, spec.direct_access_grants_enabled, spec.service_accounts_enabled), (False, True, True, False))


class TestSetupRealmClientUser:
    """setup_realm_client_user の全手順。"""

    def test_fresh_run_creates_everything(self, kc):
        """何も無い状態から、レルム・クライアント・ユーザーを作成し、シークレットとパスワード設定まで行う。"""
        _fresh_environment(kc)
        result = _run(kc)
        check.equal((result.realm.created, result.client.created, result.user.created), (True, True, True))
        check.equal((result.client.id, result.user.id, result.client_secret), ("cid-1", "uid-1", SECRET))
        check.equal([(r.method, r.path) for r in kc.writes], [("POST", R), ("POST", CLIENTS), ("POST", USERS), ("PUT", f"{USERS}/uid-1/reset-password")])
        check.equal(kc.requests_to("PUT")[0].json, {"type": "password", "temporary": False, "value": PASSWORD})

    def test_progress_messages_for_fresh_run(self, kc):
        """進捗メッセージは旧シェルスクリプトと同じ 6 ステップ(新規作成)。秘匿値は含まない。"""
        _fresh_environment(kc)
        messages: list[str] = []
        _run(kc, messages)
        check.equal(
            messages,
            [
                "[1/6] Get admin access token",
                "[2/6] Ensure realm exists: tenant-a",
                "  - Realm created",
                "[3/6] Ensure client exists: fastapi-app",
                "  - Client created",
                "[4/6] Fetch client secret",
                "[5/6] Ensure user exists: alice",
                "  - User created",
                "[6/6] Set user password",
            ],
        )
        joined = "\n".join(messages)
        check.is_not_in(SECRET, joined)
        check.is_not_in(PASSWORD, joined)

    def test_rerun_is_idempotent(self, kc):
        """作成済みなら新規作成せず、クライアント設定の反映とパスワード上書きだけを行う。"""
        _existing_environment(kc)
        messages: list[str] = []
        result = _run(kc, messages)
        check.equal((result.realm.created, result.client.created, result.client.updated, result.user.created), (False, False, True, False))
        check.equal(kc.requests_to("POST"), [])
        check.equal([(r.method, r.path) for r in kc.requests_to("PUT")], [("PUT", f"{CLIENTS}/cid-1"), ("PUT", f"{USERS}/uid-1/reset-password")])
        check.is_in("  - Realm already exists", messages)
        check.is_in("  - Client already exists", messages)
        check.is_in("  - Ensure client settings (directAccessGrants / redirect URIs)", messages)
        check.is_in("  - User already exists", messages)

    def test_admin_token_is_fetched_once(self, kc):
        """手順全体でトークンは 1 回だけ取得する(キャッシュ)。"""
        _fresh_environment(kc)
        _run(kc)
        check.equal(len(kc.tokens), 1)

    def test_invalid_realm_name_sends_no_requests(self, kc):
        """不正なレルム名は ValueError で、書き込みは行わない。"""
        with pytest.raises(ValueError):
            setup_realm_client_user(kc.admin, realm="bad realm", client_spec=_spec(), username="alice", password=PASSWORD)
        check.equal(kc.api_requests, [])

    def test_auth_failure_stops_before_any_api_call(self, kc):
        """管理トークンが取れなければ AuthError で、API は呼ばない。"""
        kc.token_response = httpx.Response(401, json={"error": "invalid_grant", "error_description": "Invalid user credentials"})
        with pytest.raises(KeycloakAdminAuthError):
            _run(kc)
        check.equal(kc.api_requests, [])

    def test_public_client_without_secret_fails_and_never_sets_password(self, kc):
        """シークレットが空(public クライアント)なら失敗し、ユーザー作成やパスワード設定へ進まない。"""
        _fresh_environment(kc)
        kc.on("GET", f"{CLIENTS}/cid-1/client-secret", json={})
        with pytest.raises(KeycloakAdminError, match="client secret is empty"):
            _run(kc)
        check.equal(kc.requests_to("POST", USERS), [])
        check.equal(kc.requests_to("PUT", f"{USERS}/uid-1/reset-password"), [])

    def test_password_failure_does_not_expose_password(self, kc):
        """パスワード設定の失敗でも、例外にパスワードもシークレットも出ない。"""
        _fresh_environment(kc)
        kc.on("PUT", f"{USERS}/uid-1/reset-password", httpx.Response(400, json={"errorMessage": "Invalid password: minimum length 8."}))
        with pytest.raises(KeycloakAdminError) as exc_info:
            _run(kc)
        check.is_not_in(PASSWORD, str(exc_info.value))
        check.is_not_in(SECRET, str(exc_info.value))

    def test_user_is_created_with_username_only(self, kc):
        """ユーザーはユーザー名だけで作成する(メール・姓・名は付けない。旧スクリプトと同じ)。"""
        _fresh_environment(kc)
        _run(kc)
        check.equal(kc.requests_to("POST", USERS)[0].json, {"username": "alice", "enabled": True, "emailVerified": False})
