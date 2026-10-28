# -*- coding: utf-8 -*-
"""TenantProvisioningService の停止・再開・削除要求(suspend / resume / request_deletion)と、状態遷移の許可・拒否の網羅テスト。"""
import datetime as dt

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.services.errors import (
    DeletionGracePeriodNotElapsedError,
    InvalidTenantTransitionError,
    TenantNotFoundError,
    TenantRealmOperationError,
    TenantValidationError,
    TenantVersionConflictError,
)
from modules.keycloak_admin.errors import KeycloakAdminError

from .conftest import initial_admin

ALL_STATUSES = [s.value for s in TenantStatus]


def setup_active_tenant(cp_db, fake_kc, *, status="ACTIVE", version=1):
    """台帳に状態を指定してテナントを作り、フェイクの Keycloak に(有効な)レルムを用意する。"""
    tenant_id = cp_db.insert_tenant(status=status, version=version)
    realm = cp_db.tenant(tenant_id)["realm_name"]
    fake_kc.realms[realm] = status == "ACTIVE"
    return tenant_id, realm


class TestSuspendResume:
    """停止・再開。"""

    def test_suspend_disables_realm_and_records(self, cp_db, make_service, fake_kc):
        """停止すると、レルムを無効化し、台帳は SUSPENDED(バージョン +1)、監査ログ tenant.suspend を残す。"""
        tenant_id, realm = setup_active_tenant(cp_db, fake_kc)
        view = make_service().suspend(tenant_id, actor="cp-admin", request_id="req-s")
        check.equal(fake_kc.calls_of("set_realm_enabled"), [{"realm_name": realm, "enabled": False}])
        check.equal(fake_kc.realms[realm], False)
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], row["updated_by"]), ("SUSPENDED", 2, "cp-admin"))
        check.equal((view.status, view.version), ("SUSPENDED", 2))
        audit = cp_db.audits(tenant_id)
        check.equal([a["action"] for a in audit], ["tenant.suspend"])
        check.equal((audit[0]["actor"], audit[0]["request_id"]), ("cp-admin", "req-s"))
        check.equal(audit[0]["payload"], {"status": {"before": "ACTIVE", "after": "SUSPENDED"}, "version": {"before": 1, "after": 2}})

    def test_resume_enables_realm(self, cp_db, make_service, fake_kc):
        """再開すると、レルムを有効化し、台帳は ACTIVE に戻る。"""
        tenant_id, realm = setup_active_tenant(cp_db, fake_kc, status="SUSPENDED")
        view = make_service().resume(tenant_id, actor="cp-admin")
        check.equal(fake_kc.calls_of("set_realm_enabled"), [{"realm_name": realm, "enabled": True}])
        check.equal((view.status, view.version), ("ACTIVE", 2))
        check.equal(cp_db.audit_actions(tenant_id), ["tenant.resume"])

    def test_suspend_then_resume_roundtrip(self, cp_db, make_service, fake_kc):
        """停止 → 再開で元の状態に戻り、バージョンは 3 になる。"""
        tenant_id, realm = setup_active_tenant(cp_db, fake_kc)
        service = make_service()
        service.suspend(tenant_id, actor="a")
        service.resume(tenant_id, actor="a")
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], fake_kc.realms[realm]), ("ACTIVE", 3, True))

    def test_keycloak_failure_leaves_state_unchanged(self, cp_db, make_service, fake_kc):
        """Keycloak の切り替えが失敗したら TenantRealmOperationError。状態・バージョン・監査ログは変えず、detail を残さない。"""
        tenant_id, realm = setup_active_tenant(cp_db, fake_kc)
        fake_kc.fail_once("set_realm_enabled", KeycloakAdminError("disable realm tenant-x", 500, "errorMessage=SECRET-DETAIL"))
        with pytest.raises(TenantRealmOperationError) as exc_info:
            make_service().suspend(tenant_id, actor="cp-admin")
        check.equal((exc_info.value.step, exc_info.value.error_summary), ("disable_realm", "step=disable_realm; error=KeycloakAdminError; http_status=500"))
        check.is_not_in("SECRET-DETAIL", str(exc_info.value))
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), ("ACTIVE", 1))
        check.equal(cp_db.audits(tenant_id), [])
        make_service().suspend(tenant_id, actor="cp-admin")
        check.equal(cp_db.tenant(tenant_id)["status"], "SUSPENDED")

    def test_resume_without_realm_fails_and_keeps_suspended(self, cp_db, make_service, fake_kc):
        """再開時にレルムが存在しない(404)場合は TenantRealmOperationError。SUSPENDED のまま。"""
        tenant_id = cp_db.insert_tenant(status="SUSPENDED")
        with pytest.raises(TenantRealmOperationError) as exc_info:
            make_service().resume(tenant_id, actor="cp-admin")
        check.is_in("http_status=404", exc_info.value.error_summary)
        check.equal(cp_db.tenant(tenant_id)["status"], "SUSPENDED")

    def test_unexpected_error_propagates_and_changes_nothing(self, cp_db, make_service, fake_kc):
        """Keycloak 以外の予期しない例外はそのまま伝わり、状態は変わらない。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc)
        fake_kc.fail_once("set_realm_enabled", RuntimeError("unexpected"))
        with pytest.raises(RuntimeError):
            make_service().suspend(tenant_id, actor="cp-admin")
        check.equal(cp_db.tenant(tenant_id)["status"], "ACTIVE")

    def test_row_is_locked_during_realm_switch(self, cp_db, make_service, fake_kc):
        """レルムの切り替え中は台帳の行をロックしている(同時の別操作が割り込めない)。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc)
        seen = {}

        def probe(kwargs):
            with cp_db.runtime.connect() as connection:
                try:
                    connection.execute(text("SELECT 1 FROM t_tenant WHERE id = :id FOR UPDATE NOWAIT"), {"id": tenant_id})
                    seen["locked"] = False
                except OperationalError:
                    seen["locked"] = True

        fake_kc.hooks["set_realm_enabled"] = probe
        make_service().suspend(tenant_id, actor="cp-admin")
        check.equal(seen["locked"], True)

    def test_unknown_tenant(self, make_service):
        """存在しないテナントは TenantNotFoundError。"""
        import uuid

        with pytest.raises(TenantNotFoundError):
            make_service().suspend(uuid.uuid4(), actor="cp-admin")

    @pytest.mark.parametrize("actor", ["", "  ", None])
    def test_actor_required(self, cp_db, make_service, fake_kc, actor):
        """操作者が空なら TenantValidationError。Keycloak は呼ばない。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc)
        with pytest.raises(TenantValidationError):
            make_service().suspend(tenant_id, actor=actor)
        check.equal(fake_kc.calls, [])


class TestRequestDeletion:
    """削除要求(猶予期間の起点)。"""

    @pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED"])
    def test_disables_realm_and_sets_deadline(self, cp_db, make_service, fake_kc, clock, status):
        """レルムを無効化し、PENDING_DELETION・削除要求日時(時計の現在時刻)を記録する。監査ログに削除可能日時(30 日後)を残す。"""
        tenant_id, realm = setup_active_tenant(cp_db, fake_kc, status=status)
        fake_kc.realms[realm] = True
        view = make_service().request_deletion(tenant_id, actor="cp-admin")
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], fake_kc.realms[realm]), ("PENDING_DELETION", 2, False))
        check.equal(row["deletion_requested_at"], clock.now)
        check.equal(view.deletion_requested_at, clock.now)
        payload = cp_db.audits(tenant_id)[0]["payload"]
        check.equal(cp_db.audit_actions(tenant_id), ["tenant.request_deletion"])
        check.equal(payload["deletion_requested_at"], clock.now.isoformat())
        check.equal(payload["deletable_at"], (clock.now + dt.timedelta(days=30)).isoformat())
        check.is_not_in("realm", payload)

    def test_failed_tenant_without_realm_skips_disable(self, cp_db, make_service, fake_kc):
        """払い出しに失敗してレルムが無い FAILED のテナントは、無効化を省略して削除要求できる(監査ログに realm=not_found)。"""
        tenant_id = cp_db.insert_tenant(status="FAILED")
        view = make_service().request_deletion(tenant_id, actor="cp-admin")
        check.equal(view.status, "PENDING_DELETION")
        check.equal(cp_db.audits(tenant_id)[0]["payload"]["realm"], "not_found")

    def test_keycloak_failure_keeps_state(self, cp_db, make_service, fake_kc):
        """無効化に失敗(404 以外)したら TenantRealmOperationError。状態は変えず、削除要求日時も残さない。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc)
        fake_kc.fail_once("set_realm_enabled", KeycloakAdminError("x", 503))
        with pytest.raises(TenantRealmOperationError):
            make_service().request_deletion(tenant_id, actor="cp-admin")
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], row["deletion_requested_at"]), ("ACTIVE", 1, None))

    def test_cannot_request_twice(self, cp_db, make_service, fake_kc):
        """削除要求済み(PENDING_DELETION)への再要求は InvalidTenantTransitionError(猶予期間の起点を変えない)。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc)
        service = make_service()
        service.request_deletion(tenant_id, actor="cp-admin")
        first = cp_db.tenant(tenant_id)["deletion_requested_at"]
        with pytest.raises(InvalidTenantTransitionError):
            service.request_deletion(tenant_id, actor="cp-admin")
        check.equal(cp_db.tenant(tenant_id)["deletion_requested_at"], first)


class TestOptimisticLock:
    """楽観ロック(expected_version)。"""

    @pytest.mark.parametrize("operation", ["suspend", "request_deletion"])
    def test_stale_version_is_rejected_before_calling_keycloak(self, cp_db, make_service, fake_kc, operation):
        """バージョン不一致は TenantVersionConflictError(412 相当)。Keycloak を呼ばず、状態も変えない。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc, version=3)
        with pytest.raises(TenantVersionConflictError) as exc_info:
            getattr(make_service(), operation)(tenant_id, actor="cp-admin", expected_version=2)
        check.equal((exc_info.value.expected_version, exc_info.value.actual_version), (2, 3))
        check.equal(fake_kc.calls, [])
        check.equal((cp_db.tenant(tenant_id)["status"], cp_db.tenant(tenant_id)["version"]), ("ACTIVE", 3))

    def test_resume_checks_version(self, cp_db, make_service, fake_kc):
        """再開もバージョンを確認する。一致すれば実行される。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc, status="SUSPENDED", version=4)
        with pytest.raises(TenantVersionConflictError):
            make_service().resume(tenant_id, actor="cp-admin", expected_version=3)
        make_service().resume(tenant_id, actor="cp-admin", expected_version=4)
        check.equal(cp_db.tenant(tenant_id)["status"], "ACTIVE")

    def test_none_skips_the_check(self, cp_db, make_service, fake_kc):
        """expected_version を指定しなければ確認しない。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc, version=7)
        make_service().suspend(tenant_id, actor="cp-admin")
        check.equal(cp_db.tenant(tenant_id)["version"], 8)

    def test_view_version_is_usable_as_if_match(self, cp_db, make_service, fake_kc):
        """戻り値のバージョン(ETag の元)を使った次の操作は成功し、古いバージョンを使うと失敗する。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc)
        service = make_service()
        suspended = service.suspend(tenant_id, actor="cp-admin", expected_version=1)
        service.resume(tenant_id, actor="cp-admin", expected_version=suspended.version)
        with pytest.raises(TenantVersionConflictError):
            service.suspend(tenant_id, actor="cp-admin", expected_version=suspended.version)

    def test_state_check_applies_even_with_matching_version(self, cp_db, make_service, fake_kc):
        """状態が許可されていない操作は、バージョンが一致していても InvalidTenantTransitionError になる。"""
        tenant_id, _ = setup_active_tenant(cp_db, fake_kc, status="SUSPENDED", version=2)
        with pytest.raises(InvalidTenantTransitionError):
            make_service().suspend(tenant_id, actor="cp-admin", expected_version=2)


# 操作 → 許可される現在の状態(01 §6.1)。それ以外の状態では InvalidTenantTransitionError になる。
ALLOWED = {
    "suspend": {"ACTIVE": "SUSPENDED"},
    "resume": {"SUSPENDED": "ACTIVE"},
    "request_deletion": {"ACTIVE": "PENDING_DELETION", "SUSPENDED": "PENDING_DELETION", "FAILED": "PENDING_DELETION"},
}


class TestTransitionMatrix:
    """全操作 × 全状態の許可・拒否。拒否では、台帳・履歴・監査ログ・Keycloak のいずれも変更しない。"""

    @pytest.mark.parametrize("status", ALL_STATUSES)
    @pytest.mark.parametrize("operation", list(ALLOWED))
    def test_operations(self, cp_db, make_service, fake_kc, operation, status):
        """停止・再開・削除要求は、遷移表で許された状態でだけ成功し、遷移先の状態になる。"""
        tenant_id, realm = setup_active_tenant(cp_db, fake_kc, status=status, version=5)
        expected_target = ALLOWED[operation].get(status)
        service = make_service()
        if expected_target is None:
            with pytest.raises(InvalidTenantTransitionError) as exc_info:
                getattr(service, operation)(tenant_id, actor="cp-admin")
            check.equal((exc_info.value.current_status, exc_info.value.operation), (status, operation))
            check.equal(fake_kc.calls, [])
            row = cp_db.tenant(tenant_id)
            check.equal((row["status"], row["version"]), (status, 5))
            check.equal((cp_db.audits(tenant_id), cp_db.histories(tenant_id)), ([], []))
        else:
            if status == "FAILED":
                fake_kc.realms.pop(realm, None)  # 払い出しに失敗してレルムが無い状況
            view = getattr(service, operation)(tenant_id, actor="cp-admin")
            check.equal(view.status, expected_target)
            row = cp_db.tenant(tenant_id)
            check.equal((row["status"], row["version"]), (expected_target, 6))

    @pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s not in ("PENDING_DELETION", "DEPROVISIONING")])
    def test_deprovision_rejected_outside_deletion_states(self, cp_db, make_service, fake_kc, fake_app_data, status):
        """物理削除は PENDING_DELETION / DEPROVISIONING 以外では InvalidTenantTransitionError。AP データも Keycloak も触らない。"""
        tenant_id = cp_db.insert_tenant(status=status, version=5)
        with pytest.raises(InvalidTenantTransitionError) as exc_info:
            make_service().deprovision(tenant_id)
        check.is_false(isinstance(exc_info.value, DeletionGracePeriodNotElapsedError))
        check.equal((fake_kc.calls, fake_app_data.calls), ([], []))
        check.equal((cp_db.tenant(tenant_id)["status"], cp_db.tenant(tenant_id)["version"]), (status, 5))
        check.equal((cp_db.audits(tenant_id), cp_db.histories(tenant_id)), ([], []))

    @pytest.mark.parametrize("status", ["ACTIVE", "SUSPENDED", "PENDING_DELETION", "DEPROVISIONING", "DELETED"])
    def test_retry_rejected_outside_failed(self, cp_db, make_service, fake_kc, status):
        """再実行は FAILED / PROVISIONING 以外では拒否される(詳細は test_20_retry.py)。"""
        tenant_id = cp_db.insert_tenant(status=status)
        with pytest.raises(InvalidTenantTransitionError):
            make_service().retry(tenant_id, initial_admin=initial_admin(), actor="cp-admin")
        check.equal(fake_kc.calls, [])

    def test_deleted_is_terminal_for_everything(self, cp_db, make_service, fake_kc, fake_app_data):
        """DELETED のテナントには、どの操作も通らない。"""
        tenant_id = cp_db.insert_tenant(status="DELETED")
        service = make_service()
        for operation in ("suspend", "resume", "request_deletion", "deprovision"):
            with pytest.raises(InvalidTenantTransitionError):
                getattr(service, operation)(tenant_id, **({"actor": "cp-admin"} if operation != "deprovision" else {}))
        with pytest.raises(InvalidTenantTransitionError):
            service.retry(tenant_id, initial_admin=initial_admin(), actor="cp-admin")
        check.equal((fake_kc.calls, fake_app_data.calls), ([], []))
