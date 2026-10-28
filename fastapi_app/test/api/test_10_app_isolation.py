# -*- coding: utf-8 -*-
"""GET /api/v1/me(AP)とテナント分離・プレーン分離のテスト(tenant-isolation スキル §5.1)。

シードのテナント alpha / beta は読み取りだけ(変更しない)。状態を変える確認は使い捨てテナントで行う。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text

from .conftest import cookie_header, with_csrf

ME = "/api/v1/me"


class TestMe:
    """/api/v1/me は、セッションのテナントとユーザーだけを返す。"""

    @pytest.mark.parametrize("code", ["alpha", "beta"])
    def test_returns_own_tenant_only(self, client, login_ap, seeded, code):
        """シードのテナントのユーザーは、自分のテナントのコードとレジストリ上の ID、自分のユーザー情報を受け取る。"""
        record = seeded(code)
        response = client.get(ME, headers=login_ap(code, record.tenant_id, ["member"], sub=f"{code}-sub-1"))
        check.equal(response.status_code, 200)
        check.equal(response.json(), {
            "tenant": {"id": str(record.tenant_id), "tenant_code": code},
            "user": {"id": f"{code}-sub-1", "username": f"{code}-member", "email": f"{code}-member@example.com", "roles": ["member"]},
        })
        check.is_in("application/json", response.headers["content-type"])

    def test_the_two_tenants_never_mix(self, client, login_ap, seeded):
        """alpha と beta のユーザーが交互にアクセスしても、それぞれ自分のテナントだけが返る。"""
        alpha, beta = seeded("alpha"), seeded("beta")
        cookies = {"alpha": login_ap("alpha", alpha.tenant_id), "beta": login_ap("beta", beta.tenant_id)}
        for code in ("alpha", "beta", "beta", "alpha"):
            body = client.get(ME, headers=cookies[code]).json()
            check.equal(body["tenant"]["tenant_code"], code)
            check.equal(body["tenant"]["id"], str(seeded(code).tenant_id))

    def test_request_values_for_tenant_are_ignored(self, client, login_ap, seeded):
        """クエリ・ヘッダー・本文に別テナントの tenant_id / tenant_code を混ぜても無視され、alpha として処理される。"""
        alpha, beta = seeded("alpha"), seeded("beta")
        headers = {**login_ap("alpha", alpha.tenant_id), "X-Tenant-ID": str(beta.tenant_id), "X-Tenant-Code": "beta", "Tenant-Id": str(beta.tenant_id)}
        response = client.request(
            "GET", ME, headers=headers, params={"tenant_id": str(beta.tenant_id), "tenant_code": "beta", "realm": "tenant-beta"},
            json={"tenant_id": str(beta.tenant_id), "tenant_code": "beta"},
        )
        check.equal(response.status_code, 200)
        check.equal(response.json()["tenant"], {"id": str(alpha.tenant_id), "tenant_code": "alpha"})

    def test_cookie_claiming_other_tenant_id_is_rejected(self, client, login_ap, seeded):
        """alpha のレルムのセッションが beta の tenant_id を名乗っても 403(tenant_unavailable)。beta の情報は返らない。"""
        alpha, beta = seeded("alpha"), seeded("beta")
        response = client.get(ME, headers=login_ap("alpha", alpha.tenant_id, claim_tenant_id=beta.tenant_id))
        check.equal(response.status_code, 403)
        check.equal(response.json()["code"], "tenant_unavailable")
        check.is_not_in(str(beta.tenant_id), response.text)
        check.is_not_in("beta", response.text.replace("tenant_unavailable", ""))

    def test_unregistered_realm_is_rejected_like_mismatch(self, client, login_ap):
        """レジストリに無いテナントのセッションは 403(tenant_unavailable)。不一致と同じコードで、存在有無を推測させない。"""
        response = client.get(ME, headers=login_ap("ghost-tenant", uuid.uuid4()))
        check.equal((response.status_code, response.json()["code"]), (403, "tenant_unavailable"))

    def test_unauthenticated(self, client):
        """Cookie が無ければ 401(unauthenticated)。"""
        response = client.get(ME)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))

    def test_garbage_cookie(self, client):
        """でたらめな Cookie は 401。"""
        check.equal(client.get(ME, headers=cookie_header(rf_sid_app="not-a-signed-value")).status_code, 401)

    def test_post_is_method_not_allowed(self, client, login_ap, seeded):
        """/me は GET だけ。POST は 405(method_not_allowed)の Problem Details。"""
        headers = with_csrf(login_ap("alpha", seeded("alpha").tenant_id))
        response = client.post(ME, headers=headers)
        check.equal((response.status_code, response.json()["code"]), (405, "method_not_allowed"))


class TestPlaneSeparation:
    """AP と CP のセッションは互いに通用しない。"""

    def test_cp_cookie_cannot_use_me(self, client, admin):
        """CP の Cookie(rf_sid_cp)では /api/v1/me に入れない(401)。"""
        response = client.get(ME, headers=admin)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))

    def test_cp_cookie_value_under_ap_cookie_name_is_rejected(self, client, admin):
        """CP の Cookie の値を AP の Cookie 名(rf_sid_app)で送っても 401(署名の salt がプレーンごとに違う)。"""
        value = admin["Cookie"].split("=", 1)[1]
        check.equal(client.get(ME, headers=cookie_header(rf_sid_app=value)).status_code, 401)

    @pytest.mark.parametrize("path", ["/api/v1/cp/tenants", "/api/v1/cp/metrics/summary"])
    def test_ap_cookie_cannot_use_cp(self, client, login_ap, seeded, path):
        """AP の Cookie(rf_sid_app)では /api/v1/cp に入れない(401)。AP のロールが tenant_admin でも同じ。"""
        headers = login_ap("alpha", seeded("alpha").tenant_id, ["tenant_admin", "member"])
        response = client.get(path, headers=headers)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))

    def test_ap_cookie_value_under_cp_cookie_name_is_rejected(self, client, login_ap, seeded):
        """AP の Cookie の値を CP の Cookie 名(rf_sid_cp)で送っても 401。"""
        value = login_ap("alpha", seeded("alpha").tenant_id)["Cookie"].split("=", 1)[1]
        check.equal(client.get("/api/v1/cp/tenants", headers=cookie_header(rf_sid_cp=value)).status_code, 401)

    def test_both_cookies_at_once(self, client, login_ap, admin, seeded):
        """同一ブラウザで AP と CP に同時ログインしていても、各ルートは自プレーンの Cookie だけを見る。"""
        both = {"Cookie": f"{login_ap('alpha', seeded('alpha').tenant_id)['Cookie']}; {admin['Cookie']}"}
        check.equal(client.get(ME, headers=both).json()["tenant"]["tenant_code"], "alpha")
        check.equal(client.get("/api/v1/cp/tenants", headers=both, params={"limit": 1}).status_code, 200)

    def test_cp_user_with_app_role_names_has_no_cp_access(self, client, login_cp):
        """CP のセッションに saas_* 以外(AP のロール名)しか無ければ、CP でも 403。"""
        response = client.get("/api/v1/cp/tenants", headers=login_cp(["tenant_admin", "member"]))
        check.equal((response.status_code, response.json()["code"]), (403, "forbidden"))


class TestInactiveTenantSessions:
    """停止中・削除要求中などのテナントのセッションは 403。使い捨てテナントで確認する。"""

    @pytest.mark.parametrize("status", ["SUSPENDED", "PENDING_DELETION", "PROVISIONING", "FAILED", "DEPROVISIONING"])
    def test_non_active_statuses_are_forbidden(self, client, cp_db, login_ap, status):
        """ACTIVE 以外のテナント(DB の状態を直接設定)は、セッションがあっても 403(tenant_inactive)。"""
        tenant_id = cp_db.insert_tenant(status=status)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        response = client.get(ME, headers=login_ap(code, tenant_id))
        check.equal((response.status_code, response.json()["code"]), (403, "tenant_inactive"))

    def test_deleted_tenant_is_forbidden_without_revealing_state(self, client, cp_db, login_ap):
        """削除済みのテナントはレジストリに現れないため、tenant_unavailable の 403(状態を明かさない)。"""
        tenant_id = cp_db.insert_tenant(status="DELETED")
        code = cp_db.tenant(tenant_id)["tenant_code"]
        response = client.get(ME, headers=login_ap(code, tenant_id))
        check.equal((response.status_code, response.json()["code"]), (403, "tenant_unavailable"))

    def test_active_tenant_works(self, client, cp_db, login_ap):
        """対照: ACTIVE の使い捨てテナントは 200。"""
        tenant_id = cp_db.insert_tenant(status="ACTIVE")
        code = cp_db.tenant(tenant_id)["tenant_code"]
        check.equal(client.get(ME, headers=login_ap(code, tenant_id)).status_code, 200)

    def test_lifecycle_through_the_api_takes_effect_immediately(self, client, make_tenant, login_ap, admin):
        """API で作成 → 停止 → 再開 → 削除要求。AP のアクセスは ACTIVE のときだけ通り、停止・削除要求の直後から 403 になる。"""
        payload = make_tenant()
        tenant = payload["tenant"]
        tenant_id, code = uuid.UUID(tenant["id"]), tenant["tenant_code"]
        user = login_ap(code, tenant_id)
        check.equal(client.get(ME, headers=user).status_code, 200)

        suspended = client.post(f"/api/v1/cp/tenants/{tenant_id}/suspend", headers=with_csrf(admin, **{"If-Match": f'"{tenant["version"]}"'}))
        check.equal(suspended.status_code, 200, suspended.text)
        response = client.get(ME, headers=user)
        check.equal((response.status_code, response.json()["code"]), (403, "tenant_inactive"))

        resumed = client.post(f"/api/v1/cp/tenants/{tenant_id}/resume", headers=with_csrf(admin, **{"If-Match": suspended.headers["ETag"]}))
        check.equal(resumed.status_code, 200, resumed.text)
        check.equal(client.get(ME, headers=user).status_code, 200)

        deleted = client.delete(f"/api/v1/cp/tenants/{tenant_id}", headers=with_csrf(admin, **{"If-Match": resumed.headers["ETag"]}))
        check.equal(deleted.status_code, 200, deleted.text)
        check.equal(deleted.json()["status"], "PENDING_DELETION")
        response = client.get(ME, headers=user)
        check.equal((response.status_code, response.json()["code"]), (403, "tenant_inactive"))

    def test_one_tenant_suspension_does_not_affect_another(self, client, make_tenant, login_ap, admin, seeded):
        """使い捨てテナントを停止しても、alpha のユーザーは引き続き利用できる。"""
        tenant = make_tenant()["tenant"]
        client.post(f"/api/v1/cp/tenants/{tenant['id']}/suspend", headers=with_csrf(admin, **{"If-Match": f'"{tenant["version"]}"'}))
        check.equal(client.get(ME, headers=login_ap("alpha", seeded("alpha").tenant_id)).status_code, 200)

    def test_alpha_and_beta_are_untouched(self, cp_db, seeded):
        """前提の確認: シードのテナントは ACTIVE のまま(このテストファイルが変更していない)。"""
        for code in ("alpha", "beta"):
            seeded(code)
            with cp_db.runtime.connect() as connection:
                status = connection.execute(text("SELECT status FROM t_tenant WHERE tenant_code = :c"), {"c": code}).scalar()
            check.equal(status, "ACTIVE")
