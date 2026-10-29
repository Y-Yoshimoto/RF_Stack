# -*- coding: utf-8 -*-
"""遷移先の定義(modules.auth.redirects)、認証状態・ログアウト、開発用ログインの遷移先、OpenAPI の表現のテスト。

``main_app.route.auth`` のルーターだけをマウントした最小のアプリで確認する(app.py は使わない)。
Redis はインメモリの代替。Keycloak へは通信しない。テナントレジストリは固定の代替、AP のユーザー同期は差し替える (DB に接続しない)。
"""
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_check as check
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main_app.route.auth import apiapp, dev_login
from main_app.services.errors import UserDeactivatedError
from main_app.services.user_sync import UserSyncResult
from modules.auth import session
from modules.auth.csrf import install_csrf_openapi
from modules.auth.plane import Plane
from modules.auth.redirects import LoginErrorCode, login_error_path, login_page_path, post_login_path
from modules.errors.openapi import install_problem_openapi
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord

from .conftest import make_session_data

FRONTEND = "http://localhost:5173"
CSRF = {"X-Requested-With": "rf-stack", "Origin": FRONTEND}
ALPHA = TenantRecord(tenant_id=uuid.UUID("0194e6a0-0000-7000-8000-00000000a1fa"), tenant_code="alpha", realm_name="tenant-alpha", status="ACTIVE")
BETA = TenantRecord(tenant_id=uuid.UUID("0194e6a0-0000-7000-8000-00000000b2fb"), tenant_code="beta", realm_name="tenant-beta", status="ACTIVE")


class FixedRegistry:
    """レルムで引くテナントレジストリの代替。"""

    def __init__(self, *records: TenantRecord) -> None:
        self.records = list(records)

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        return next((r for r in self.records if r.tenant_code == tenant_code), None)

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        return next((r for r in self.records if r.realm_name == realm_name), None)

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        return next((r for r in self.records if r.tenant_id == tenant_id), None)


@pytest.fixture
def registry() -> FixedRegistry:
    return FixedRegistry(ALPHA, BETA)


def _cookie(**cookies: str) -> dict[str, str]:
    """リクエストヘッダーとして Cookie を渡す。"""
    return {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


@pytest.fixture
def app(config, registry, monkeypatch) -> FastAPI:
    """auth のルーター(と開発用ログイン)を /api/auth にマウントしたアプリ。OpenAPI の後処理も app.py と同じ。"""
    monkeypatch.setattr(apiapp, "_config", config)
    monkeypatch.setattr(dev_login, "_config", config)
    application = FastAPI()
    application.include_router(apiapp.router, prefix="/api/auth", tags=["auth"])
    application.include_router(dev_login.router, prefix="/api/auth", tags=["auth"])
    application.dependency_overrides[get_tenant_registry] = lambda: registry
    install_problem_openapi(application)
    install_csrf_openapi(application)
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, follow_redirects=False)


class TestRedirectPaths:
    """遷移先のパス(01 §11.1 のフロントエンドのルーティング)。"""

    def test_post_login(self):
        """ログイン成功: AP は /{tenant_code}/、CP は /cp/。テナントが分からなければ /。"""
        check.equal(post_login_path(Plane.APP, "alpha"), "/alpha/")
        check.equal(post_login_path(Plane.CP), "/cp/")
        check.equal(post_login_path(Plane.CP, "alpha"), "/cp/", "CP はテナントコードを使わない")
        check.equal(post_login_path(Plane.APP, None), "/")

    def test_login_page(self):
        """ログイン画面(ログアウト後の遷移先): AP は /{tenant_code}/login、CP は /cp/login。"""
        check.equal(login_page_path(Plane.APP, "alpha"), "/alpha/login")
        check.equal(login_page_path(Plane.CP), "/cp/login")
        check.equal(login_page_path(Plane.APP, None), "/")

    def test_login_error(self):
        """失敗: プレーン・テナントが分かればそのログイン画面、分からなければ / に ?error=<code>。"""
        check.equal(login_error_path(LoginErrorCode.TENANT_UNAVAILABLE), "/?error=tenant_unavailable")
        check.equal(login_error_path(LoginErrorCode.LOGIN_REJECTED, Plane.CP), "/cp/login?error=login_rejected")
        check.equal(login_error_path(LoginErrorCode.INVALID_TOKEN, Plane.APP, "alpha"), "/alpha/login?error=invalid_token")
        check.equal(login_error_path(LoginErrorCode.INVALID_TOKEN, Plane.APP, None), "/?error=invalid_token")

    @pytest.mark.parametrize("tenant_code", ["", "ab", "../x", "a/b", "//evil.example.com", "ALPHA", "alpha?x=1", "alpha#x", "alpha\n"])
    def test_malformed_tenant_code_falls_back_to_landing(self, tenant_code):
        """形式に合わないテナントコードはパスに連結せず / にする(パス操作・オープンリダイレクトをしない)。"""
        check.equal(post_login_path(Plane.APP, tenant_code), "/")
        check.equal(login_page_path(Plane.APP, tenant_code), "/")
        check.equal(login_error_path(LoginErrorCode.LOGIN_REJECTED, Plane.APP, tenant_code), "/?error=login_rejected")

    def test_urls_are_always_on_the_frontend_origin(self, config):
        """URL のホスト部は常に FRONTEND_URL。"""
        check.equal(config.post_login_url(Plane.APP, "alpha"), f"{FRONTEND}/alpha/")
        check.equal(config.post_logout_url(Plane.APP, "alpha"), f"{FRONTEND}/alpha/login")
        check.equal(config.post_logout_url(Plane.CP), f"{FRONTEND}/cp/login")
        check.equal(config.post_login_url(Plane.APP, "//evil.example.com"), f"{FRONTEND}/")


class TestStatus:
    """GET /api/auth/{app,cp}/status。"""

    def test_app_status_returns_tenant_code_and_user_only(self, client, login_as):
        """AP の状態はテナントコードとユーザー(sub / preferred_username / email / roles)。レルム・tenant_id・トークンは返さない。"""
        cookie, _ = login_as(Plane.APP, ["tenant_admin"])
        response = client.get("/api/auth/app/status", headers=_cookie(rf_sid_app=cookie))
        check.equal(response.status_code, 200)
        check.equal(
            response.json(),
            {
                "authenticated": True,
                "plane": "app",
                "tenant_code": "alpha",
                "user": {"sub": "user-sub-1", "preferred_username": "tester", "email": "tester@example.com", "roles": ["tenant_admin"]},
            },
        )
        for secret in ("tenant-alpha", "11111111-1111-7111-8111-111111111111", "access-token-value", "refresh-token-value", "id-token-value"):
            check.is_not_in(secret, response.text)

    def test_cp_status(self, client, login_as):
        """CP の状態はユーザーのみ(tenant_code を持たない)。"""
        cookie, _ = login_as(Plane.CP, ["saas_viewer"])
        response = client.get("/api/auth/cp/status", headers=_cookie(rf_sid_cp=cookie))
        check.equal(response.status_code, 200)
        check.equal(response.json()["plane"], "cp")
        check.is_not_in("tenant_code", response.json())
        check.equal(response.json()["user"]["roles"], ["saas_viewer"])

    def test_status_requires_the_plane_session(self, client, login_as):
        """Cookie が無い、または別プレーンのセッションしか無ければ 401。"""
        app_cookie, _ = login_as(Plane.APP, ["member"])
        cp_cookie, _ = login_as(Plane.CP, ["saas_admin"])
        check.equal(client.get("/api/auth/app/status").status_code, 401)
        check.equal(client.get("/api/auth/cp/status").status_code, 401)
        check.equal(client.get("/api/auth/app/status", headers=_cookie(rf_sid_cp=cp_cookie)).status_code, 401)
        check.equal(client.get("/api/auth/cp/status", headers=_cookie(rf_sid_app=app_cookie)).status_code, 401)
        check.equal(client.get("/api/auth/app/status", headers=_cookie(rf_sid_app=cp_cookie)).status_code, 401, "CP の署名を AP の Cookie 名で送っても不可")


class TestLogout:
    """POST /api/auth/{app,cp}/logout。"""

    def _logout_query(self, response) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(urlsplit(response.json()["logout_url"]).query).items()}

    def test_app_logout_returns_to_tenant_login(self, client, login_as, fake_redis):
        """AP のログアウトはセッションを消して Cookie を削除し、Keycloak のログアウト後に /{tenant_code}/login へ戻る URL を返す。CP のセッションは残す。"""
        app_cookie, app_sid = login_as(Plane.APP, ["member"])
        cp_cookie, cp_sid = login_as(Plane.CP, ["saas_admin"])
        response = client.post("/api/auth/app/logout", headers={**CSRF, **_cookie(rf_sid_app=app_cookie, rf_sid_cp=cp_cookie)})
        check.equal(response.status_code, 200)
        check.equal(set(response.json()), {"logout_url"})
        check.is_true(response.json()["logout_url"].startswith("http://localhost:8080/keycloak/realms/tenant-alpha/protocol/openid-connect/logout?"))
        query = self._logout_query(response)
        check.equal(query["post_logout_redirect_uri"], f"{FRONTEND}/alpha/login")
        check.equal(query["client_id"], "fastapi-app")
        check.is_none(session.get_session(Plane.APP, app_sid))
        check.is_not_none(session.get_session(Plane.CP, cp_sid))
        set_cookie = response.headers["set-cookie"]
        check.is_true(set_cookie.startswith('rf_sid_app=""') or set_cookie.startswith("rf_sid_app=;"), set_cookie)
        check.is_in("max-age=0", set_cookie.lower())
        check.is_not_in("rf_sid_cp", set_cookie)

    def test_cp_logout_returns_to_cp_login(self, client, login_as):
        """CP のログアウト後は /cp/login。"""
        cp_cookie, _ = login_as(Plane.CP, ["saas_admin"])
        response = client.post("/api/auth/cp/logout", headers={**CSRF, **_cookie(rf_sid_cp=cp_cookie)})
        check.equal(self._logout_query(response)["post_logout_redirect_uri"], f"{FRONTEND}/cp/login")
        check.is_true(response.headers["set-cookie"].startswith("rf_sid_cp="))

    def test_logout_without_session_returns_login_page(self, client):
        """セッションが無くても 200 で、ログイン画面の URL を返す(AP はテナントが分からないので /)。"""
        check.equal(client.post("/api/auth/cp/logout", headers=CSRF).json(), {"logout_url": f"{FRONTEND}/cp/login"})
        check.equal(client.post("/api/auth/app/logout", headers=CSRF).json(), {"logout_url": f"{FRONTEND}/"})

    def test_logout_requires_csrf_headers(self, client, login_as):
        """X-Requested-With または Origin が無ければ 403 で、セッションは消さない。"""
        cookie, sid = login_as(Plane.APP, ["member"])
        check.equal(client.post("/api/auth/app/logout", headers={"Origin": FRONTEND, **_cookie(rf_sid_app=cookie)}).status_code, 403)
        check.equal(client.post("/api/auth/app/logout", headers={"X-Requested-With": "rf-stack", **_cookie(rf_sid_app=cookie)}).status_code, 403)
        check.is_not_none(session.get_session(Plane.APP, sid))


class TestDevLoginRedirect:
    """GET /api/auth/dev-login の遷移先(Keycloak への通信とトークン検証は差し替える)。"""

    @pytest.fixture(autouse=True)
    def stub(self, monkeypatch, fake_redis) -> dict:
        """トークン取得・検証・ユーザー同期を差し替え、呼び出しを記録する。"""
        recorded: dict = {"fetch": [], "build": [], "sync": [], "sync_error": None}

        def fake_fetch(profile):
            recorded["fetch"].append(profile.username)
            return {"access_token": "a", "refresh_token": "r", "id_token": "i"}

        def fake_build(config, plane, realm, token_data, *, expected_nonce, tenant_code=None, expected_tenant_id=None):
            recorded["build"].append({"plane": plane, "tenant_code": tenant_code, "expected_tenant_id": expected_tenant_id})
            if plane == Plane.APP:
                return make_session_data(plane, roles=["tenant_admin"], realm=realm, tenant_code=tenant_code)
            return make_session_data(plane, roles=["saas_admin"], realm=realm)

        def fake_sync(session_data, *, tenant_id, tenant_code):
            sessions = [key for key in fake_redis.keys() if key.startswith("session:")]
            recorded["sync"].append({"tenant_id": tenant_id, "tenant_code": tenant_code, "sub": session_data["user"]["sub"], "sessions_before": sessions})
            if recorded["sync_error"] is not None:
                raise recorded["sync_error"]
            return UserSyncResult(user_id=uuid.uuid4(), created=True, profile_updated=False, email_conflict=False, default_organization_id=None)

        monkeypatch.setattr(dev_login, "_fetch_tokens", fake_fetch)
        monkeypatch.setattr(dev_login, "build_login_session", fake_build)
        monkeypatch.setattr(dev_login, "sync_app_user_on_login", fake_sync)
        return recorded

    @pytest.mark.parametrize(("profile", "location", "cookie"), [("alpha-admin", "/alpha/", "rf_sid_app"), ("beta-member", "/beta/", "rf_sid_app"), ("cp-admin", "/cp/", "rf_sid_cp")])
    def test_default_next(self, client, profile, location, cookie):
        """next 省略時: AP のプロファイルは /{tenant_code}/、CP は /cp/。"""
        response = client.get("/api/auth/dev-login", params={"as": profile})
        check.equal((response.status_code, response.headers["location"]), (302, f"{FRONTEND}{location}"))
        check.is_true(response.headers["set-cookie"].startswith(f"{cookie}="))

    def test_default_profile_is_alpha_admin(self, client):
        """as も next も省略すると alpha-admin で /alpha/ へ。"""
        check.equal(client.get("/api/auth/dev-login").headers["location"], f"{FRONTEND}/alpha/")

    def test_next_path_is_kept(self, client):
        """next に同一オリジンのパスを渡せばそこへ。"""
        check.equal(client.get("/api/auth/dev-login", params={"next": "/alpha/todos?x=1"}).headers["location"], f"{FRONTEND}/alpha/todos?x=1")

    @pytest.mark.parametrize("next_path", ["https://evil.example.com", "//evil.example.com", "/\\evil.example.com", "alpha/"])
    def test_next_must_be_a_path(self, client, next_path):
        """next がパス以外ならリダイレクトせず 400。"""
        check.equal(client.get("/api/auth/dev-login", params={"next": next_path}).status_code, 400)

    def test_replaces_existing_session_of_the_same_plane(self, client, login_as):
        """同じプレーンの既存セッションは破棄する(Cookie はリクエストから読む)。"""
        cookie, sid = login_as(Plane.APP, ["member"])
        client.get("/api/auth/dev-login", headers=_cookie(rf_sid_app=cookie))
        check.is_none(session.get_session(Plane.APP, sid))

    def test_app_profile_syncs_with_registry_tenant_before_creating_the_session(self, client, stub):
        """AP のプロファイルは、レジストリのテナントで tenant_id クレームを確認し、セッションを作る前に 1 回だけ同期する。"""
        response = client.get("/api/auth/dev-login", params={"as": "alpha-member"})
        check.equal(response.status_code, 302)
        check.equal(stub["build"][0]["expected_tenant_id"], str(ALPHA.tenant_id))
        check.equal(len(stub["sync"]), 1)
        call = stub["sync"][0]
        check.equal((call["tenant_id"], call["tenant_code"], call["sub"]), (ALPHA.tenant_id, "alpha", "user-sub-1"))
        check.equal(call["sessions_before"], [], "同期の時点ではセッションを作っていない")

    def test_deactivated_user_is_rejected_without_a_session(self, client, stub, fake_redis):
        """無効化されたユーザーは 403(Login rejected)で、セッションも Cookie も作らない。"""
        stub["sync_error"] = UserDeactivatedError(uuid.uuid4())
        response = client.get("/api/auth/dev-login", params={"as": "alpha-member"})
        check.equal((response.status_code, response.json()["detail"]), (403, "Login rejected"))
        check.is_not_in("rf_sid_", response.headers.get("set-cookie", ""))
        check.equal([key for key in fake_redis.keys() if key.startswith("session:")], [])

    @pytest.mark.parametrize("profile", ["cp-admin", "cp-viewer"])
    def test_cp_profile_does_not_sync(self, client, stub, profile):
        """CP のプロファイルではユーザー同期を呼ばず、tenant_id の確認もしない。"""
        check.equal(client.get("/api/auth/dev-login", params={"as": profile}).status_code, 302)
        check.equal(stub["sync"], [])
        check.is_none(stub["build"][0]["expected_tenant_id"])

    @pytest.mark.parametrize(
        ("records", "detail"),
        [
            ((BETA,), "tenant_not_found"),
            ((TenantRecord(ALPHA.tenant_id, "alpha", "tenant-alpha", "SUSPENDED"), BETA), "tenant_inactive"),
            ((TenantRecord(ALPHA.tenant_id, "other", "tenant-alpha", "ACTIVE"), BETA), "tenant_mismatch"),
        ],
        ids=["unregistered", "suspended", "code-mismatch"],
    )
    def test_unavailable_tenant_is_rejected_before_fetching_tokens(self, client, stub, registry, records, detail):
        """AP のテナントが未登録・ACTIVE でない・テナントコードが食い違う場合は 403 で、トークン取得・同期へ進まない。"""
        registry.records = list(records)
        response = client.get("/api/auth/dev-login", params={"as": "alpha-member"})
        check.equal((response.status_code, response.json()["detail"]), (403, detail))
        check.equal((stub["fetch"], stub["sync"]), ([], []))


class TestOpenApi:
    """OpenAPI での表現(02 §5.6)。"""

    @pytest.fixture
    def spec(self, app) -> dict:
        return app.openapi()

    def test_only_status_and_logout_are_documented(self, spec):
        """status / logout は載せ、login / callback / dev-login(リダイレクト)は載せない。"""
        operations = {(method, path) for path, item in spec["paths"].items() for method in item}
        check.equal(
            operations,
            {("get", "/api/auth/app/status"), ("get", "/api/auth/cp/status"), ("post", "/api/auth/app/logout"), ("post", "/api/auth/cp/logout")},
        )

    def test_response_models_and_problem_responses(self, spec):
        """status は 200 の型と 401、logout は 200 の型と 403 を Problem Details で記述する。"""
        paths = spec["paths"]
        for path, model, error in (
            ("/api/auth/app/status", "AppAuthStatus", "401"),
            ("/api/auth/cp/status", "CpAuthStatus", "401"),
        ):
            responses = paths[path]["get"]["responses"]
            check.equal(responses["200"]["content"]["application/json"]["schema"]["$ref"], f"#/components/schemas/{model}", path)
            check.equal(responses[error]["content"]["application/problem+json"]["schema"]["$ref"], "#/components/schemas/ProblemDetails", path)
            check.is_not_in("422", responses, path)
        for path in ("/api/auth/app/logout", "/api/auth/cp/logout"):
            responses = paths[path]["post"]["responses"]
            check.equal(responses["200"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/LogoutResult", path)
            check.equal(responses["403"]["content"]["application/problem+json"]["schema"]["$ref"], "#/components/schemas/ProblemDetails", path)
            check.is_not_in("422", responses, path)
        check.equal(spec["components"]["schemas"]["AppAuthStatus"]["required"], ["authenticated", "plane", "tenant_code", "user"])

    def test_session_cookie_is_a_security_scheme_not_a_parameter(self, spec):
        """セッション Cookie はパラメータではなくセキュリティスキーム(AppSession / CpSession)。"""
        schemes = spec["components"]["securitySchemes"]
        check.equal(schemes["AppSession"], {**schemes["AppSession"], "type": "apiKey", "in": "cookie", "name": "rf_sid_app"})
        check.equal(schemes["CpSession"], {**schemes["CpSession"], "type": "apiKey", "in": "cookie", "name": "rf_sid_cp"})
        check.equal(spec["paths"]["/api/auth/app/status"]["get"]["security"], [{"AppSession": []}])
        check.equal(spec["paths"]["/api/auth/cp/status"]["get"]["security"], [{"CpSession": []}])
        cookie_params = [(path, p["name"]) for path, item in spec["paths"].items() for op in item.values() for p in op.get("parameters", []) if p["in"] == "cookie"]
        check.equal(cookie_params, [])

    def test_logout_requires_csrf_header(self, spec):
        """logout は X-Requested-With: rf-stack を必須のヘッダーとして記述する。status(参照系)には載せない。"""
        for path in ("/api/auth/app/logout", "/api/auth/cp/logout"):
            parameters = spec["paths"][path]["post"]["parameters"]
            check.equal([(p["in"], p["name"], p["required"], p["schema"]["enum"]) for p in parameters], [("header", "X-Requested-With", True, ["rf-stack"])], path)
        check.is_not_in("parameters", spec["paths"]["/api/auth/app/status"]["get"])
