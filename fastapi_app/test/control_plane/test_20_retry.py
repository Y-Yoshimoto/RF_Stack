# -*- coding: utf-8 -*-
"""TenantProvisioningService.retry(失敗・中断した払い出しの再実行)のテスト。"""
import uuid

import pytest
import pytest_check as check

from control_plane_app.repositories.locks import PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.errors import (
    InvalidTenantTransitionError,
    ProvisioningFailedError,
    TenantNotFoundError,
    TenantOperationInProgressError,
    TenantValidationError,
    TenantVersionConflictError,
)
from modules.keycloak_admin.errors import KeycloakAdminError

from .conftest import SENTINEL_PASSWORD, initial_admin


def failed_tenant(cp_db, make_service, fake_kc, *, step="ensure_tenant_realm"):
    """払い出しに失敗して FAILED になったテナント(ID, コード)を作る。"""
    code = cp_db.new_code()
    fake_kc.fail_once(step, KeycloakAdminError("create", 500, "boom"))
    with pytest.raises(ProvisioningFailedError):
        make_service().onboard(tenant_code=code, name="Retry Corp", initial_admin=initial_admin(), actor="cp-admin")
    return cp_db.tenant_by_code(code)["id"], code


def retry(service, tenant_id, **overrides):
    values = {"initial_admin": initial_admin(), "actor": "cp-admin-2", "request_id": "req-retry"}
    values.update(overrides)
    return service.retry(tenant_id, **values)


class TestRetrySuccess:
    """FAILED からの再実行。"""

    def test_failed_to_active(self, cp_db, make_service, fake_kc):
        """FAILED のテナントを再実行すると ACTIVE になる。バージョンは 2(FAILED)→3(PROVISIONING)→4(ACTIVE)。"""
        tenant_id, code = failed_tenant(cp_db, make_service, fake_kc)
        fake_kc.calls.clear()
        result = retry(make_service(), tenant_id)
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], row["updated_by"], row["created_by"]), ("ACTIVE", 4, "cp-admin-2", "cp-admin"))
        check.equal((result.tenant.status, result.tenant.version), ("ACTIVE", 4))
        check.equal(fake_kc.names(), ["ensure_tenant_realm", "ensure_tenant_user"])
        check.equal(fake_kc.calls_of("ensure_tenant_realm")[0]["tenant_id"], tenant_id)
        check.equal(fake_kc.calls_of("ensure_tenant_realm")[0]["tenant_code"], code)

    def test_history_and_audit(self, cp_db, make_service, fake_kc):
        """履歴は 失敗(FAILED)→再実行(SUCCEEDED) の 2 件、監査ログは create → provision_fail → provision_retry → provision_succeed。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        retry(make_service(), tenant_id)
        check.equal([(h["status"], h["step"]) for h in cp_db.histories(tenant_id)], [("FAILED", "ensure_tenant_realm"), ("SUCCEEDED", "activate")])
        check.equal(cp_db.audit_actions(tenant_id), ["tenant.create", "tenant.provision_fail", "tenant.provision_retry", "tenant.provision_succeed"])
        retry_audit = cp_db.audits(tenant_id)[2]
        check.equal((retry_audit["actor"], retry_audit["request_id"]), ("cp-admin-2", "req-retry"))
        check.equal(retry_audit["payload"]["status"], {"before": "FAILED", "after": "PROVISIONING"})

    def test_new_temporary_password_is_issued(self, cp_db, make_service, fake_kc):
        """再実行では新しい一時パスワードを発行して設定する(前回の値は無効になる)。どちらも DB に残らない。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc, step="ensure_tenant_user")
        generated = iter(["First-Passw0rd-AAA1!", "Second-Passw0rd-BBB2!"])
        result = retry(make_service(password_generator=lambda: next(generated)), tenant_id)
        check.equal(result.temporary_password, "First-Passw0rd-AAA1!")
        check.equal(fake_kc.passwords[-1], "First-Passw0rd-AAA1!")
        check.not_equal(fake_kc.passwords[-1], SENTINEL_PASSWORD, "最初の失敗時に生成した値は再利用しない")
        for value in ("First-Passw0rd-AAA1!", SENTINEL_PASSWORD):
            check.is_not_in(value, cp_db.dump_text(tenant_id))

    def test_initial_admin_is_specified_again(self, cp_db, make_service, fake_kc):
        """初期管理者は台帳に無いため再実行時の指定が使われる。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        retry(make_service(), tenant_id, initial_admin=initial_admin(email="other@Example.com", username="Root"))
        user_call = fake_kc.calls_of("ensure_tenant_user")[-1]
        check.equal((user_call["username"], user_call["email"]), ("root", "other@Example.com"))

    def test_retry_fails_again_stays_retryable(self, cp_db, make_service, fake_kc):
        """再実行も失敗したら FAILED に戻り、さらに再実行できる。履歴は失敗ごとに残る。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        fake_kc.fail_once("ensure_tenant_user", KeycloakAdminError("x", 502))
        with pytest.raises(ProvisioningFailedError) as exc_info:
            retry(make_service(), tenant_id)
        check.equal(exc_info.value.step, "ensure_initial_admin")
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), ("FAILED", 4))
        check.equal(len(cp_db.histories(tenant_id)), 2)
        retry(make_service(), tenant_id)
        check.equal(cp_db.tenant(tenant_id)["status"], "ACTIVE")
        check.equal(len(cp_db.histories(tenant_id)), 3)

    def test_interrupted_provisioning_is_retryable(self, cp_db, make_service, fake_kc):
        """プロセス停止などで PROVISIONING のまま残った(実行中の処理が無い)テナントも再実行でき、RUNNING のまま残った履歴は閉じる。"""
        tenant_id = cp_db.insert_tenant(status="PROVISIONING", with_running_history=True)
        retry(make_service(), tenant_id)
        by_status = {h["status"]: h for h in cp_db.histories(tenant_id)}
        check.equal(sorted(by_status), ["FAILED", "SUCCEEDED"], "RUNNING のまま残らない")
        check.equal(by_status["FAILED"]["error"], "step=ensure_tenant_realm; error=interrupted")
        check.is_not_none(by_status["FAILED"]["finished_at"])
        check.equal(cp_db.tenant(tenant_id)["status"], "ACTIVE")


class TestRetryRejections:
    """再実行できない場合。いずれも台帳・Keycloak に変更を加えない。"""

    @pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED", "PENDING_DELETION", "DEPROVISIONING", "DELETED"])
    def test_wrong_state(self, cp_db, make_service, fake_kc, status):
        """FAILED / PROVISIONING 以外の状態では InvalidTenantTransitionError(409)。"""
        tenant_id = cp_db.insert_tenant(status=status, version=5)
        with pytest.raises(InvalidTenantTransitionError) as exc_info:
            retry(make_service(), tenant_id)
        check.equal((exc_info.value.current_status, exc_info.value.operation), (status, "retry"))
        check.equal(fake_kc.calls, [])
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), (status, 5))
        check.equal((cp_db.audits(tenant_id), cp_db.histories(tenant_id)), ([], []))

    def test_unknown_tenant(self, make_service, fake_kc):
        """存在しないテナントは TenantNotFoundError(404)。"""
        with pytest.raises(TenantNotFoundError):
            retry(make_service(), uuid.uuid4())
        check.equal(fake_kc.calls, [])

    def test_invalid_initial_admin_is_checked_first(self, cp_db, make_service, fake_kc):
        """初期管理者が不正なら TenantValidationError。状態は FAILED のまま。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        fake_kc.calls.clear()
        with pytest.raises(TenantValidationError):
            retry(make_service(), tenant_id, initial_admin=initial_admin(email="bad"))
        check.equal(cp_db.tenant(tenant_id)["status"], "FAILED")
        check.equal(fake_kc.calls, [])

    def test_operation_in_progress(self, cp_db, make_service, fake_kc):
        """払い出しが実行中(ロック保持中)なら TenantOperationInProgressError。PROVISIONING のテナントでも状態は変えない。"""
        tenant_id = cp_db.insert_tenant(status="PROVISIONING", with_running_history=True)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        with PgAdvisoryLock(cp_db.runtime).try_acquire(tenant_lock_key(code)) as acquired:
            check.is_true(acquired)
            with pytest.raises(TenantOperationInProgressError):
                retry(make_service(), tenant_id)
        check.equal(fake_kc.calls, [])
        check.equal([h["status"] for h in cp_db.histories(tenant_id)], ["RUNNING"], "実行中の履歴を閉じない")
        check.equal(cp_db.tenant(tenant_id)["status"], "PROVISIONING")

    @pytest.mark.parametrize("actor", ["", None])
    def test_actor_required(self, cp_db, make_service, actor):
        """操作者が空なら TenantValidationError。"""
        tenant_id = cp_db.insert_tenant(status="FAILED")
        with pytest.raises(TenantValidationError):
            retry(make_service(), tenant_id, actor=actor)


class TestRetryOptimisticLock:
    """楽観ロック(expected_version。If-Match)。"""

    def test_stale_version_is_rejected_before_any_change(self, cp_db, make_service, fake_kc):
        """バージョンが一致しなければ TenantVersionConflictError(expected / actual 付き)。Keycloak も台帳も変更しない。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        fake_kc.calls.clear()
        with pytest.raises(TenantVersionConflictError) as exc_info:
            retry(make_service(), tenant_id, expected_version=1)
        check.equal((exc_info.value.expected_version, exc_info.value.actual_version), (1, 2))
        check.equal(fake_kc.calls, [])
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), ("FAILED", 2))

    def test_matching_version_passes(self, cp_db, make_service, fake_kc):
        """バージョンが一致すれば実行される。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        retry(make_service(), tenant_id, expected_version=2)
        check.equal(cp_db.tenant(tenant_id)["status"], "ACTIVE")

    def test_second_caller_with_old_version_loses(self, cp_db, make_service, fake_kc):
        """同じバージョンを持つ 2 人が続けて実行すると、後の人は(状態が変わっているので)拒否される。"""
        tenant_id, _ = failed_tenant(cp_db, make_service, fake_kc)
        retry(make_service(), tenant_id, expected_version=2)
        with pytest.raises((TenantVersionConflictError, InvalidTenantTransitionError)):
            retry(make_service(), tenant_id, expected_version=2)
        check.equal(cp_db.tenant(tenant_id)["version"], 4)
