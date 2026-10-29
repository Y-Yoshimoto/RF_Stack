# -*- coding: utf-8 -*-
"""/api/v1/cp の認可(saas_admin / saas_viewer)と CSRF 対策のテスト。"""
import uuid

import pytest
import pytest_check as check

from .conftest import ADMIN_SUB, CSRF_HEADERS, with_csrf

TENANTS = "/api/v1/cp/tenants"
ANY_ID = "0194e6a0-0000-7000-8000-00000000f00d"
READ_PATHS = [TENANTS, f"{TENANTS}/{ANY_ID}", f"{TENANTS}/{ANY_ID}/metrics", "/api/v1/cp/metrics/summary"]
# (メソッド, パス, 本文)。変更系は saas_admin のみ
WRITE_CALLS = [
    ("POST", TENANTS, {"tenant_code": "zt-authz-x", "name": "X", "initial_admin": {"email": "a@example.com"}}),
    ("POST", f"{TENANTS}/{ANY_ID}/suspend", None),
    ("POST", f"{TENANTS}/{ANY_ID}/resume", None),
    ("DELETE", f"{TENANTS}/{ANY_ID}", None),
    ("POST", f"{TENANTS}/{ANY_ID}/provisioning/retry", {"initial_admin": {"email": "a@example.com"}}),
]


def call(client, method, path, body, headers):
    return client.request(method, path, json=body, headers=headers)


class TestAuthentication:
    """未認証・ロール無し。"""

    @pytest.mark.parametrize("path", READ_PATHS)
    def test_reads_require_login(self, client, path):
        """Cookie が無ければ参照系も 401(unauthenticated)。"""
        response = client.get(path)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))

    @pytest.mark.parametrize(("method", "path", "body"), WRITE_CALLS)
    def test_writes_require_login_before_csrf(self, client, method, path, body):
        """未認証の変更系は CSRF のヘッダーが無くても 403 ではなく 401(認証が先)。"""
        response = call(client, method, path, body, {})
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))

    @pytest.mark.parametrize("path", READ_PATHS)
    def test_user_without_cp_role_is_forbidden(self, client, login_cp, path):
        """CP のセッションでも saas_* のロールが無ければ 403(forbidden)。"""
        response = client.get(path, headers=login_cp([]))
        check.equal((response.status_code, response.json()["code"]), (403, "forbidden"))


class TestViewerIsReadOnly:
    """saas_viewer は参照だけ。"""

    @pytest.mark.parametrize("path", [TENANTS, "/api/v1/cp/metrics/summary"])
    def test_viewer_can_read(self, client, viewer, path):
        """参照系は saas_viewer でも 200。"""
        check.equal(client.get(path, headers=viewer).status_code, 200)

    @pytest.mark.parametrize(("method", "path", "body"), WRITE_CALLS)
    def test_viewer_cannot_write(self, client, viewer, cp_db, method, path, body):
        """変更系は(CSRF のヘッダーが正しくても)403(forbidden)。If-Match があっても同じで、何も作成・変更されない。"""
        headers = with_csrf(viewer, **{"If-Match": '"1"'})
        response = call(client, method, path, body, headers)
        check.equal((response.status_code, response.json()["code"]), (403, "forbidden"))
        check.is_none(cp_db.tenant_by_code("zt-authz-x"))

    def test_viewer_cannot_write_without_if_match_either(self, client, viewer):
        """権限の無い変更系は、If-Match が無くても 428 ではなく 403(認可が前提条件の確認より先)。"""
        response = client.post(f"{TENANTS}/{ANY_ID}/suspend", headers=with_csrf(viewer))
        check.equal((response.status_code, response.json()["code"]), (403, "forbidden"))

    def test_admin_with_both_roles_is_allowed(self, client, login_cp):
        """saas_admin と saas_viewer の両方を持つユーザーは変更系も通る(存在しないテナントなので 404)。"""
        headers = with_csrf(login_cp(["saas_admin", "saas_viewer"]), **{"If-Match": '"1"'})
        response = client.post(f"{TENANTS}/{uuid.uuid4()}/suspend", headers=headers)
        check.equal((response.status_code, response.json()["code"]), (404, "tenant_not_found"))


class TestCsrf:
    """変更系の CSRF 対策(X-Requested-With + 許可オリジン)。"""

    def create_body(self, cp_db):
        return {"tenant_code": cp_db.new_code(), "name": "Csrf Test", "initial_admin": {"email": "a@example.com"}}

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"Origin": CSRF_HEADERS["Origin"]},  # カスタムヘッダー無し
            {"X-Requested-With": "rf-stack"},  # Origin 無し
            {"X-Requested-With": "rf-stack", "Origin": "http://evil.example.com"},  # 他オリジン
            {"X-Requested-With": "rf-stack", "Origin": "null"},
            {"X-Requested-With": "rf-stack", "Origin": "http://localhost:5173.evil.example.com"},
            {"X-Requested-With": "true", "Origin": CSRF_HEADERS["Origin"]},  # 値が違う
        ],
        ids=["no-headers", "no-custom-header", "no-origin", "other-origin", "null-origin", "prefix-trick", "wrong-header-value"],
    )
    def test_create_is_rejected_and_nothing_is_created(self, client, admin, cp_db, extra):
        """管理者でも CSRF 対策が満たされない POST は 403(csrf_validation_failed)で、テナントは作成されない。"""
        body = self.create_body(cp_db)
        response = client.post(TENANTS, json=body, headers={**admin, **extra})
        check.equal((response.status_code, response.json()["code"]), (403, "csrf_validation_failed"))
        check.is_none(cp_db.tenant_by_code(body["tenant_code"]))

    @pytest.mark.parametrize(("method", "suffix"), [("POST", "/suspend"), ("POST", "/resume"), ("DELETE", ""), ("POST", "/provisioning/retry")])
    def test_other_mutations_are_protected(self, client, admin, method, suffix):
        """停止・再開・削除要求・再実行も CSRF 対策の対象(403)。"""
        body = {"initial_admin": {"email": "a@example.com"}} if suffix.endswith("retry") else None
        response = client.request(method, f"{TENANTS}/{ANY_ID}{suffix}", json=body, headers={**admin, "If-Match": '"1"'})
        check.equal((response.status_code, response.json()["code"]), (403, "csrf_validation_failed"))

    def test_reads_do_not_need_csrf_headers(self, client, admin):
        """GET は CSRF のヘッダー無しで通る。"""
        check.equal(client.get(TENANTS, headers=admin, params={"limit": 1}).status_code, 200)

    def test_allowed_origin_passes(self, client, admin, cp_db):
        """許可オリジン + カスタムヘッダーがあれば作成できる(201)。"""
        body = self.create_body(cp_db)
        response = client.post(TENANTS, json=body, headers=with_csrf(admin))
        check.equal(response.status_code, 201, response.text)
        cp_db.tenant_by_code(body["tenant_code"])

    def test_csrf_trusted_origins_extension(self, client, admin, cp_db, monkeypatch):
        """CSRF_TRUSTED_ORIGINS に足したオリジンも許可される。"""
        from modules.auth import csrf
        from modules.auth.environment import KeyCloakEnvironmentVariables

        monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "http://localhost:4173")
        monkeypatch.setattr(csrf, "_config", KeyCloakEnvironmentVariables())
        body = self.create_body(cp_db)
        response = client.post(TENANTS, json=body, headers={**admin, "X-Requested-With": "rf-stack", "Origin": "http://localhost:4173"})
        check.equal(response.status_code, 201, response.text)
        cp_db.tenant_by_code(body["tenant_code"])

    def test_csrf_is_also_applied_to_ap_router(self, client, login_ap, seeded):
        """AP のルーター(/api/v1)にも同じ CSRF 対策がある(GET の /me は素通り)。"""
        headers = login_ap("alpha", seeded("alpha").tenant_id)
        check.equal(client.get("/api/v1/me", headers=headers).status_code, 200)

    def test_actor_is_the_cp_users_subject(self, client, admin, cp_db):
        """操作者(created_by・監査ログの actor)は CP セッションの sub であり、リクエストの値ではない。"""
        body = self.create_body(cp_db)
        response = client.post(TENANTS, json={**body, "actor": "someone-else", "created_by": "someone-else"}, headers=with_csrf(admin, **{"X-Actor": "someone-else"}))
        check.equal(response.status_code, 201, response.text)
        row = cp_db.tenant_by_code(body["tenant_code"])
        check.equal((row["created_by"], row["updated_by"]), (ADMIN_SUB, ADMIN_SUB))
        check.is_true(all(a["actor"] == ADMIN_SUB for a in cp_db.audits(row["id"])))
