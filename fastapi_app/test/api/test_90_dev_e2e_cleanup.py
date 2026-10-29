# -*- coding: utf-8 -*-
"""POST /api/dev/e2e-cleanup(E2E データの後片付け API。開発専用。docs/architecture/02 §5.6・05 #33)のテスト。

- 認証・認可(CP の ``saas_admin``)・CSRF 対策は実物の依存関数を通す。後片付けの本体(``cleanup_e2e_data``)は差し替えて、開発 DB の他のデータを消さない。
- 実際の削除を通すテストは、使い捨ての E2E のテナントだけを走査する ``ScopedCleaner`` に差し替える(``dev_cleanup/conftest.py``)。
- 開発専用機能が無効な場合にルートが登録されないことは、環境変数を変えて ``app.py`` を別名で読み込み直して確認する(共有の ``app`` は変更しない)。
"""
import importlib.util
import sys
import uuid

import pytest
import pytest_check as check
from dev_cleanup.conftest import _dev_env, calls, clock, make_cleaner, new_e2e_code, scan_as_seed  # noqa: F401
from dev_cleanup.conftest import e2e_tenant as e2e_tenant  # noqa: F401
from fastapi.testclient import TestClient

import app as app_module
from app import app
from dev_tools.e2e_cleanup import AppTenantCleanupCounts, CleanupFailure, E2ECleanupInProgressError, E2ECleanupNotAllowedError, E2ECleanupResult, TenantCleanupCounts
from main_app.route.dev import e2e_cleanup as route_module

from .conftest import CSRF_HEADERS, with_csrf

PATH = "/api/dev/e2e-cleanup"


class FakeCleanup:
    """``cleanup_e2e_data`` の差し替え(呼び出しの記録と、返す結果・送出する例外)。"""

    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.outcome: object = E2ECleanupResult(dry_run=False)

    def __call__(self, *, dry_run: bool = False) -> E2ECleanupResult:
        self.calls.append(dry_run)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome  # type: ignore[return-value]


@pytest.fixture
def fake_cleanup(monkeypatch) -> FakeCleanup:
    """後片付けの本体を差し替える(何も削除しない)。"""
    fake = FakeCleanup()
    monkeypatch.setattr(route_module, "cleanup_e2e_data", fake)
    return fake


class TestAuthorization:
    """CP の saas_admin だけが呼べる。拒否された場合は後片付けを呼ばない。"""

    def test_admin_gets_the_result(self, client, admin, fake_cleanup):
        """saas_admin は 200。本文は後片付けの結果(dry_run / tenants / app_tenants / failures / ok)。既定は dry_run=false。"""
        fake_cleanup.outcome = E2ECleanupResult(dry_run=False, tenants=TenantCleanupCounts(deprovisioned=2, reaped=1, skipped=1))
        fake_cleanup.outcome.app_tenants.append(AppTenantCleanupCounts(tenant_code="alpha", users=3, keycloak_users=3, todos=2))
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal(set(body), {"dry_run", "tenants", "app_tenants", "failures", "ok"})
        check.equal(body, fake_cleanup.outcome.to_dict())
        check.equal((body["tenants"]["deprovisioned"], body["app_tenants"][0]["tenant_code"], body["ok"]), (2, "alpha", True))
        check.equal(fake_cleanup.calls, [False])
        check.is_in("application/json", response.headers["content-type"])

    @pytest.mark.parametrize(("query", "expected"), [("?dry_run=true", True), ("?dry_run=false", False), ("?dry_run=1", True), ("", False)])
    def test_dry_run_query(self, client, admin, fake_cleanup, query, expected):
        """dry_run クエリを後片付けに渡す(省略時は false)。"""
        response = client.post(f"{PATH}{query}", headers=with_csrf(admin))
        check.equal(response.status_code, 200)
        check.equal(fake_cleanup.calls, [expected])

    def test_invalid_dry_run_is_422(self, client, admin, fake_cleanup):
        """dry_run が真偽値でなければ 422(Problem Details)。後片付けは呼ばない。"""
        response = client.post(f"{PATH}?dry_run=maybe", headers=with_csrf(admin))
        check.equal(response.status_code, 422)
        check.equal(fake_cleanup.calls, [])

    def test_failures_are_reported_with_200(self, client, admin, fake_cleanup):
        """失敗したテナントがあっても 200 で、ok=false と failures の内訳を返す(他のテナントの処理は続いている)。"""
        result = E2ECleanupResult(dry_run=False, tenants=TenantCleanupCounts(deprovisioned=1, failed=1))
        result.failures.append(CleanupFailure(scope="cp", tenant_code="e2e-abcd1234", error="deprovisioning_failed"))
        fake_cleanup.outcome = result
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 200)
        body = response.json()
        check.equal((body["ok"], body["failures"]), (False, [{"scope": "cp", "tenant_code": "e2e-abcd1234", "error": "deprovisioning_failed"}]))

    def test_viewer_is_forbidden(self, client, viewer, fake_cleanup):
        """saas_viewer は 403(forbidden)。後片付けは呼ばない。"""
        response = client.post(PATH, headers=with_csrf(viewer))
        check.equal((response.status_code, response.json()["code"]), (403, "forbidden"))
        check.equal(fake_cleanup.calls, [])

    def test_cp_session_without_role_is_forbidden(self, client, login_cp, fake_cleanup):
        """CP のセッションでもロールが無ければ 403。"""
        response = client.post(PATH, headers=with_csrf(login_cp([])))
        check.equal(response.status_code, 403)
        check.equal(fake_cleanup.calls, [])

    def test_ap_session_is_unauthorized(self, client, login_ap, fake_cleanup):
        """AP のセッション(Cookie)では 401。テナントの管理者でも呼べない。"""
        headers = with_csrf(login_ap("alpha", uuid.uuid4(), ["tenant_admin"]))
        response = client.post(PATH, headers=headers)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))
        check.equal(fake_cleanup.calls, [])

    def test_unauthenticated(self, client, fake_cleanup):
        """Cookie が無ければ 401(CSRF のヘッダーがあっても)。"""
        response = client.post(PATH, headers=CSRF_HEADERS)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))
        check.equal(fake_cleanup.calls, [])

    def test_garbage_cookie(self, client, fake_cleanup):
        """でたらめな Cookie は 401。"""
        response = client.post(PATH, headers=with_csrf({"Cookie": "rf_sid_cp=garbage"}))
        check.equal(response.status_code, 401)
        check.equal(fake_cleanup.calls, [])

    def test_missing_csrf_header_is_forbidden(self, client, admin, fake_cleanup):
        """saas_admin でも CSRF 対策のヘッダー(X-Requested-With と Origin)が無ければ 403。後片付けは呼ばない。"""
        response = client.post(PATH, headers=admin)
        check.equal(response.status_code, 403)
        check.equal(fake_cleanup.calls, [])

    @pytest.mark.parametrize(
        "extra",
        [{"X-Requested-With": "rf-stack"}, {"Origin": "http://localhost:5173"}, {"X-Requested-With": "rf-stack", "Origin": "http://evil.example.com"}, {"X-Requested-With": "other", "Origin": "http://localhost:5173"}],
        ids=["no-origin", "no-requested-with", "foreign-origin", "wrong-requested-with"],
    )
    def test_partial_or_wrong_csrf_headers_are_forbidden(self, client, admin, fake_cleanup, extra):
        """CSRF 対策のヘッダーの片方だけ・許可されないオリジン・値が違う場合も 403。"""
        response = client.post(PATH, headers={**admin, **extra})
        check.equal(response.status_code, 403)
        check.equal(fake_cleanup.calls, [])

    def test_unauthenticated_is_checked_before_csrf(self, client, fake_cleanup):
        """未認証でヘッダーも無い場合は 401(認証が先)。"""
        check.equal(client.post(PATH).status_code, 401)

    @pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
    def test_other_methods_are_not_allowed(self, client, admin, fake_cleanup, method):
        """POST 以外は 405(後片付けを呼ばない)。"""
        response = client.request(method, PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 405)
        check.equal(fake_cleanup.calls, [])

    def test_arguments_cannot_choose_targets(self, client, admin, fake_cleanup):
        """リクエストボディ・クエリで対象(テナント・ユーザー等)を指定しても無視され、dry_run 以外は後片付けに渡らない。"""
        response = client.post(f"{PATH}?tenant_code=alpha&email=alice@example.com", json={"tenant_code": "alpha", "emails": ["a@example.com"]}, headers=with_csrf(admin))
        check.equal(response.status_code, 200)
        check.equal(fake_cleanup.calls, [False])


class TestErrors:
    """後片付けの例外の HTTP への変換。"""

    def test_in_progress_is_409(self, client, admin, fake_cleanup):
        """別の後片付けが実行中なら 409(e2e_cleanup_in_progress)の Problem Details。"""
        fake_cleanup.outcome = E2ECleanupInProgressError("busy")
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 409)
        check.is_in("application/problem+json", response.headers["content-type"])
        body = response.json()
        check.equal((body["status"], body["code"]), (409, "e2e_cleanup_in_progress"))
        check.is_in("title", body)
        check.is_not_in("busy", response.text)

    def test_not_allowed_is_404(self, client, admin, fake_cleanup):
        """(ルートが登録されていても)開発環境でないと判定されたら 404(not_found)。環境の詳細は出さない。"""
        fake_cleanup.outcome = E2ECleanupNotAllowedError("APP_ENV=development ではありません")
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (404, "not_found"))
        check.is_not_in("APP_ENV", response.text)

    def test_unexpected_error_is_500_without_details(self, client, admin, fake_cleanup):
        """想定外の例外は 500 の Problem Details で、例外の内容は返さない。"""
        fake_cleanup.outcome = RuntimeError("secret-connection-string-XYZ")
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 500)
        check.is_not_in("secret-connection-string-XYZ", response.text)


class TestRegistration:
    """開発専用の機能が無効なら、ルート自体が登録されない(404)。OpenAPI には出ない。"""

    def load_app(self, monkeypatch, *, app_env: str, flag: str | None):
        """環境変数を変えて ``app.py`` を別名で読み込み直し、新しい FastAPI アプリを返す(共有の ``app`` は変更しない)。"""
        monkeypatch.setenv("APP_ENV", app_env)
        if flag is None:
            monkeypatch.delenv("AUTH_DEV_LOGIN_ENABLED", raising=False)
        else:
            monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", flag)
        name = f"app_copy_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(name, app_module.__file__)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
        return module.app

    def test_registered_when_dev_login_is_enabled(self, monkeypatch):
        """開発環境で開発用ログインが有効なら、ルートが登録される(dev-login と同じ条件)。"""
        fresh = self.load_app(monkeypatch, app_env="development", flag="true")
        paths = {route.path for route in fresh.routes}
        check.is_in(PATH, paths)
        check.is_in("/api/auth/dev-login", paths)

    @pytest.mark.parametrize("flag", [None, "", "false", "0"])
    def test_not_registered_when_dev_login_is_disabled(self, monkeypatch, admin, flag):
        """開発用ログインが無効(未設定・空・false)なら、ルートは存在せず 404。saas_admin の Cookie と CSRF のヘッダーがあっても同じ。"""
        fresh = self.load_app(monkeypatch, app_env="development", flag=flag)
        check.is_not_in(PATH, {route.path for route in fresh.routes})
        check.is_not_in("/api/auth/dev-login", {route.path for route in fresh.routes})
        response = TestClient(fresh, raise_server_exceptions=False).post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 404)

    def test_not_registered_in_production(self, monkeypatch, admin):
        """本番(APP_ENV=development 以外)で開発用ログインを要求していなければ、ルートは存在せず 404。"""
        monkeypatch.setenv("SESSION_SECRET_KEY", "api-test-session-secret")
        fresh = self.load_app(monkeypatch, app_env="production", flag="false")
        check.is_not_in(PATH, {route.path for route in fresh.routes})
        response = TestClient(fresh, raise_server_exceptions=False).post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 404)

    def test_enabling_in_production_fails_at_startup(self, monkeypatch):
        """本番で開発用ログインの有効化を要求すると、起動時(読み込み時)にエラーになる(ルートを登録しない)。"""
        monkeypatch.setenv("SESSION_SECRET_KEY", "api-test-session-secret")
        with pytest.raises(RuntimeError):
            self.load_app(monkeypatch, app_env="production", flag="true")

    def test_not_in_openapi_or_docs(self, client):
        """OpenAPI にも Swagger UI にも出ない(include_in_schema=False)。有効な共有の app でも同じ。"""
        spec = app.openapi()
        check.is_not_in(PATH, spec["paths"])
        check.equal([path for path in spec["paths"] if "/dev/" in path or "e2e" in path], [])
        check.is_not_in("e2e-cleanup", client.get("/openapi.json").text)
        check.is_in(PATH, {route.path for route in app.routes})

    def test_router_has_no_schema_operations(self):
        """ルーターの操作はすべてスキーマに載せない設定。"""
        check.is_true(route_module.router.routes)
        check.is_true(all(route.include_in_schema is False for route in route_module.router.routes))


class TestRealCleanupThroughApi:
    """API から実際の後片付けを通し、E2E の使い捨てテナントだけが削除されることを確認する(走査対象は ScopedCleaner で絞る)。"""

    def test_deletes_only_e2e_tenants(self, client, admin, monkeypatch, make_cleaner, e2e_tenant, cp_db, fake_kc):  # noqa: F811
        """E2E の命名のテナントは物理削除され、通常のテナント(zt-*)・命名の違う e2e-* は変わらない。応答の件数は実際の結果と一致する。"""
        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")
        target = e2e_tenant("ACTIVE")
        near_miss = e2e_tenant("ACTIVE", code="e2e-abcd12345")
        ordinary = cp_db.insert_tenant(status="ACTIVE")
        monkeypatch.setattr(route_module, "cleanup_e2e_data", lambda *, dry_run=False: make_cleaner().run(dry_run=dry_run))

        dry = client.post(f"{PATH}?dry_run=true", headers=with_csrf(admin)).json()
        check.equal((cp_db.tenant(target)["status"], dry["dry_run"], dry["tenants"]["deprovisioned"]), ("ACTIVE", True, 1))

        response = client.post(PATH, headers=with_csrf(admin))
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal((body["ok"], body["tenants"]), (True, {"deprovisioned": 1, "reaped": 0, "skipped": 0, "failed": 0}))
        check.equal(
            (cp_db.tenant(target)["status"], cp_db.tenant(near_miss)["status"], cp_db.tenant(ordinary)["status"]),
            ("DELETED", "ACTIVE", "ACTIVE"),
        )

    def test_concurrent_run_is_409(self, client, admin, monkeypatch, make_cleaner, e2e_tenant, cp_db):  # noqa: F811
        """全体のロックを別の実行が保持している間は 409 で、何も削除しない。"""
        from dev_cleanup.conftest import MemoryLock

        from dev_tools.e2e_cleanup import CLEANUP_LOCK_KEY

        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")
        target = e2e_tenant("ACTIVE")
        monkeypatch.setattr(route_module, "cleanup_e2e_data", lambda *, dry_run=False: make_cleaner(lock=MemoryLock({CLEANUP_LOCK_KEY})).run(dry_run=dry_run))
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (409, "e2e_cleanup_in_progress"))
        check.equal(cp_db.tenant(target)["status"], "ACTIVE")

    def test_refuses_when_environment_is_not_development(self, client, admin, monkeypatch, make_cleaner, e2e_tenant, cp_db):  # noqa: F811
        """ルートが登録済みでも、実行時に開発環境でなくなっていれば(後片付け本体が拒否して)404。台帳は変わらない。"""
        target = e2e_tenant("ACTIVE")
        monkeypatch.setattr(route_module, "cleanup_e2e_data", lambda *, dry_run=False: make_cleaner().run(dry_run=dry_run))
        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "false")
        response = client.post(PATH, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (404, "not_found"))
        check.equal(cp_db.tenant(target)["status"], "ACTIVE")
