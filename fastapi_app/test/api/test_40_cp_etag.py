# -*- coding: utf-8 -*-
"""停止・再開・削除要求の ETag / If-Match(楽観ロック。03 §5.2)と状態遷移のテスト。使い捨てテナントで確認する。"""
import uuid

import pytest
import pytest_check as check

from .conftest import with_csrf

TENANTS = "/api/v1/cp/tenants"
# 操作 → (メソッド, パス末尾, 実行前に必要な状態)
OPERATIONS = {
    "suspend": ("POST", "/suspend", "ACTIVE"),
    "resume": ("POST", "/resume", "SUSPENDED"),
    "delete": ("DELETE", "", "ACTIVE"),
}


@pytest.fixture
def tenant_in(cp_db, fake_kc):
    """指定の状態の使い捨てテナント(ID, バージョン)を作る。レルムはフェイクの Keycloak に用意する。"""

    def create(status: str = "ACTIVE", version: int = 2):
        tenant_id = cp_db.insert_tenant(status=status, version=version)
        fake_kc.realms[cp_db.tenant(tenant_id)["realm_name"]] = status == "ACTIVE"
        return tenant_id, version

    return create


def operate(client, admin, operation, tenant_id, if_match):
    method, suffix, _ = OPERATIONS[operation]
    headers = with_csrf(admin) if if_match is None else with_csrf(admin, **{"If-Match": if_match})
    return client.request(method, f"{TENANTS}/{tenant_id}{suffix}", headers=headers)


@pytest.mark.parametrize("operation", list(OPERATIONS))
class TestIfMatch:
    """If-Match の必須・形式・一致。"""

    def test_missing_if_match_is_428(self, client, admin, tenant_in, cp_db, fake_kc, operation):
        """If-Match が無ければ 428(precondition_required)。状態は変わらず、Keycloak も呼ばれない。"""
        tenant_id, version = tenant_in(OPERATIONS[operation][2])
        before = cp_db.tenant(tenant_id)["status"]
        response = operate(client, admin, operation, tenant_id, None)
        check.equal((response.status_code, response.json()["code"]), (428, "precondition_required"))
        check.equal((cp_db.tenant(tenant_id)["status"], cp_db.tenant(tenant_id)["version"]), (before, version))
        check.equal(fake_kc.calls, [])

    @pytest.mark.parametrize("value", ["abc", "2", "*", '"2", "3"', '""', '"0"', '"-1"', '"2.5"', '"02"', '"1e3"', '"99999999999999999999"', "W/2", 'W/"2', "'2'"])
    def test_malformed_if_match_is_400(self, client, admin, tenant_in, cp_db, fake_kc, operation, value):
        """形式が不正な If-Match(引用符なし・* ・複数・0・負数・小数など)は 400(invalid_if_match)。状態は変わらない。"""
        tenant_id, version = tenant_in(OPERATIONS[operation][2])
        response = operate(client, admin, operation, tenant_id, value)
        check.equal((response.status_code, response.json()["code"]), (400, "invalid_if_match"))
        check.equal(cp_db.tenant(tenant_id)["version"], version)
        check.equal(fake_kc.calls, [])

    def test_stale_version_is_412(self, client, admin, tenant_in, cp_db, fake_kc, operation):
        """バージョンが合わなければ 412(tenant_version_conflict)。状態は変わらず、Keycloak も呼ばれない。"""
        tenant_id, version = tenant_in(OPERATIONS[operation][2])
        for wrong in (version - 1, version + 1, 999):
            response = operate(client, admin, operation, tenant_id, f'"{wrong}"')
            check.equal((response.status_code, response.json()["code"]), (412, "tenant_version_conflict"), f"If-Match={wrong}")
        check.equal(cp_db.tenant(tenant_id)["version"], version)
        check.equal(fake_kc.calls, [])

    @pytest.mark.parametrize("weak", [False, True])
    def test_matching_version_succeeds_and_returns_new_etag(self, client, admin, tenant_in, cp_db, operation, weak):
        """一致すれば 200。本文の version と新しい ETag は更新後のバージョン(+1)。弱い検証子 W/"n" も受け付ける。"""
        tenant_id, version = tenant_in(OPERATIONS[operation][2])
        response = operate(client, admin, operation, tenant_id, f'W/"{version}"' if weak else f'"{version}"')
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal((body["version"], response.headers["ETag"]), (version + 1, f'"{version + 1}"'))
        check.equal(cp_db.tenant(tenant_id)["version"], version + 1)
        check.is_not_in("realm_name", response.text)

    def test_unknown_tenant_is_404(self, client, admin, operation):
        """存在しないテナントは、正しい形式の If-Match でも 404(tenant_not_found)。"""
        response = operate(client, admin, operation, uuid.uuid4(), '"1"')
        check.equal((response.status_code, response.json()["code"]), (404, "tenant_not_found"))

    def test_malformed_id_is_422(self, client, admin, operation):
        """UUID でない ID は 422。"""
        response = operate(client, admin, operation, "not-a-uuid", '"1"')
        check.equal(response.status_code, 422)


class TestOperations:
    """操作の結果と状態遷移。"""

    def test_suspend_then_resume_chain_of_etags(self, client, admin, viewer, tenant_in):
        """返された新しい ETag を次の操作に使い続けられる。古い ETag を使うと 412。"""
        tenant_id, version = tenant_in("ACTIVE")
        suspended = operate(client, admin, "suspend", tenant_id, f'"{version}"')
        check.equal((suspended.status_code, suspended.json()["status"]), (200, "SUSPENDED"))
        stale = operate(client, admin, "resume", tenant_id, f'"{version}"')
        check.equal(stale.status_code, 412)
        resumed = operate(client, admin, "resume", tenant_id, suspended.headers["ETag"])
        check.equal((resumed.status_code, resumed.json()["status"], resumed.headers["ETag"]), (200, "ACTIVE", f'"{version + 2}"'))
        check.equal(client.get(f"{TENANTS}/{tenant_id}", headers=viewer).headers["ETag"], resumed.headers["ETag"])

    def test_delete_requests_deletion_without_physical_delete(self, client, admin, tenant_in, cp_db):
        """DELETE は削除要求(PENDING_DELETION)で、台帳の行は残り、削除要求日時が入る。物理削除ではない。"""
        tenant_id, version = tenant_in("ACTIVE")
        response = operate(client, admin, "delete", tenant_id, f'"{version}"')
        body = response.json()
        check.equal((response.status_code, body["status"]), (200, "PENDING_DELETION"))
        check.is_not_none(body["deletion_requested_at"])
        check.is_none(body["deleted_at"])
        check.equal(cp_db.tenant(tenant_id)["status"], "PENDING_DELETION")

    @pytest.mark.parametrize(
        ("operation", "status"),
        [
            ("suspend", "SUSPENDED"), ("suspend", "FAILED"), ("suspend", "PENDING_DELETION"), ("suspend", "DELETED"),
            ("resume", "ACTIVE"), ("resume", "FAILED"), ("resume", "PENDING_DELETION"),
            ("delete", "PENDING_DELETION"), ("delete", "DEPROVISIONING"), ("delete", "DELETED"), ("delete", "PROVISIONING"),
        ],
    )
    def test_invalid_transition_is_409_with_details(self, client, admin, tenant_in, cp_db, fake_kc, operation, status):
        """許されない状態からの操作は 409(invalid_tenant_transition)。operation と current_status を返し、状態は変わらない。"""
        tenant_id, version = tenant_in(status)
        response = operate(client, admin, operation, tenant_id, f'"{version}"')
        body = response.json()
        check.equal((response.status_code, body["code"]), (409, "invalid_tenant_transition"))
        check.equal(body["current_status"], status)
        check.is_in(body["operation"], ("suspend", "resume", "request_deletion"))
        check.equal((cp_db.tenant(tenant_id)["status"], cp_db.tenant(tenant_id)["version"]), (status, version))
        check.equal(fake_kc.calls, [])

    def test_failed_tenant_can_be_deleted(self, client, admin, tenant_in):
        """FAILED のテナントは削除要求できる。"""
        tenant_id, version = tenant_in("FAILED")
        check.equal(operate(client, admin, "delete", tenant_id, f'"{version}"').json()["status"], "PENDING_DELETION")

    def test_keycloak_failure_is_502_and_state_unchanged(self, client, admin, tenant_in, cp_db, fake_kc):
        """Keycloak の切り替えに失敗したら 502(tenant_realm_operation_failed)。状態・バージョンは変わらず、本文に原因の詳細を含まない。"""
        from modules.keycloak_admin.errors import KeycloakAdminError

        tenant_id, version = tenant_in("ACTIVE")
        fake_kc.fail_once("set_realm_enabled", KeycloakAdminError("disable realm tenant-x", 500, "errorMessage=KC-INTERNAL-DETAIL"))
        response = operate(client, admin, "suspend", tenant_id, f'"{version}"')
        body = response.json()
        check.equal((response.status_code, body["code"], body["step"], body["tenant_id"]), (502, "tenant_realm_operation_failed", "disable_realm", str(tenant_id)))
        check.is_not_in("KC-INTERNAL-DETAIL", response.text)
        check.equal((cp_db.tenant(tenant_id)["status"], cp_db.tenant(tenant_id)["version"]), ("ACTIVE", version))

    def test_audit_log_has_request_id_and_actor(self, client, admin, tenant_in, cp_db):
        """監査ログには操作者(CP ユーザーの sub)とリクエスト ID(X-Request-ID)が残る。"""
        tenant_id, version = tenant_in("ACTIVE")
        method, suffix, _ = OPERATIONS["suspend"]
        response = client.request(method, f"{TENANTS}/{tenant_id}{suffix}", headers=with_csrf(admin, **{"If-Match": f'"{version}"', "X-Request-ID": "req-audit-12345"}))
        check.equal(response.headers["X-Request-ID"], "req-audit-12345")
        audit = cp_db.audits(tenant_id)[0]
        check.equal((audit["action"], audit["actor"], audit["request_id"]), ("tenant.suspend", "cp-admin-sub-0001", "req-audit-12345"))

    def test_operation_in_progress_is_409(self, client, admin, tenant_in, cp_db):
        """同じテナントの処理が実行中(排他ロック保持中)なら 409(tenant_operation_in_progress)。"""
        from control_plane_app.repositories.locks import PgAdvisoryLock, tenant_lock_key

        tenant_id, version = tenant_in("FAILED")
        code = cp_db.tenant(tenant_id)["tenant_code"]
        body = {"initial_admin": {"email": "a@example.com"}}
        with PgAdvisoryLock(cp_db.runtime).try_acquire(tenant_lock_key(code)):
            response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json=body, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (409, "tenant_operation_in_progress"))
        check.equal(cp_db.tenant(tenant_id)["version"], version)


class TestRetryIfMatch:
    """retry の If-Match は任意(指定した場合は検証する)。"""

    BODY = {"initial_admin": {"email": "retry-admin@example.com"}}

    def failed(self, cp_db):
        return cp_db.insert_tenant(status="FAILED", version=2)

    def test_optional(self, client, admin, cp_db):
        """If-Match が無くても再実行できる(200 と新しい ETag)。"""
        tenant_id = self.failed(cp_db)
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json=self.BODY, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["tenant"]["status"]), (200, "ACTIVE"))
        check.equal(response.headers["ETag"], '"4"')

    def test_stale_if_match_is_412(self, client, admin, cp_db):
        """指定した If-Match が合わなければ 412。FAILED のまま。"""
        tenant_id = self.failed(cp_db)
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json=self.BODY, headers=with_csrf(admin, **{"If-Match": '"1"'}))
        check.equal((response.status_code, response.json()["code"]), (412, "tenant_version_conflict"))
        check.equal(cp_db.tenant(tenant_id)["status"], "FAILED")

    def test_malformed_if_match_is_400(self, client, admin, cp_db):
        """形式が不正な If-Match は 400。"""
        tenant_id = self.failed(cp_db)
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json=self.BODY, headers=with_csrf(admin, **{"If-Match": "nope"}))
        check.equal((response.status_code, response.json()["code"]), (400, "invalid_if_match"))

    def test_matching_if_match_succeeds(self, client, admin, cp_db):
        """一致する If-Match なら実行される。"""
        tenant_id = self.failed(cp_db)
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json=self.BODY, headers=with_csrf(admin, **{"If-Match": '"2"'}))
        check.equal(response.status_code, 200, response.text)
