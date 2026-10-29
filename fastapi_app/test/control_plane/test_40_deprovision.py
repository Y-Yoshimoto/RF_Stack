# -*- coding: utf-8 -*-
"""TenantProvisioningService.deprovision(猶予期間後の物理削除)のテスト。"""
import datetime as dt
import uuid

import pytest
import pytest_check as check

from control_plane_app.repositories.locks import PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.errors import (
    DeletionGracePeriodNotElapsedError,
    DeprovisioningFailedError,
    InvalidTenantTransitionError,
    TenantCodeAlreadyExistsError,
    TenantNotFoundError,
    TenantOperationInProgressError,
    TenantValidationError,
)
from modules.keycloak_admin.errors import KeycloakAdminError

from .conftest import initial_admin

GRACE = dt.timedelta(days=30)


def pending_tenant(cp_db, fake_kc, clock, *, requested_ago=GRACE, realm_exists=True):
    """削除要求から ``requested_ago`` 経過した PENDING_DELETION のテナントを作る。"""
    tenant_id = cp_db.insert_tenant(status="PENDING_DELETION", version=3, deletion_requested_at=clock.now - requested_ago)
    realm = cp_db.tenant(tenant_id)["realm_name"]
    if realm_exists:
        fake_kc.realms[realm] = False
    return tenant_id, realm


class TestGracePeriod:
    """猶予期間(30 日)の判定。"""

    def test_before_grace_period_is_rejected(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """猶予期間を 1 秒でも残していれば DeletionGracePeriodNotElapsedError。何も削除せず、状態・履歴・監査ログも変えない。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=GRACE - dt.timedelta(seconds=1))
        with pytest.raises(DeletionGracePeriodNotElapsedError) as exc_info:
            make_service().deprovision(tenant_id)
        check.is_true(isinstance(exc_info.value, InvalidTenantTransitionError))
        check.equal(exc_info.value.current_status, "PENDING_DELETION")
        check.equal((fake_kc.calls, fake_app_data.calls), ([], []))
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), ("PENDING_DELETION", 3))
        check.equal((cp_db.audits(tenant_id), cp_db.histories(tenant_id)), ([], []))

    def test_exactly_at_grace_period_is_allowed(self, cp_db, make_service, fake_kc, clock):
        """ちょうど 30 日経過した時点から削除できる(境界を含む)。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=GRACE)
        result = make_service().deprovision(tenant_id)
        check.equal(result.tenant.status, "DELETED")

    def test_requested_just_now_is_rejected(self, cp_db, make_service, fake_kc, clock):
        """削除要求の直後は拒否される。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=dt.timedelta(0))
        with pytest.raises(DeletionGracePeriodNotElapsedError):
            make_service().deprovision(tenant_id)

    def test_time_passing_makes_it_allowed(self, cp_db, make_service, fake_kc, clock):
        """時計を進めると、同じテナントが削除できるようになる。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=dt.timedelta(days=10))
        with pytest.raises(DeletionGracePeriodNotElapsedError):
            make_service().deprovision(tenant_id)
        clock.advance(days=20)
        check.equal(make_service().deprovision(tenant_id).tenant.status, "DELETED")

    def test_grace_period_can_be_overridden(self, cp_db, make_service, fake_kc, clock):
        """猶予期間は引数で変えられる(短くすれば 10 日後でも、長くすれば 30 日後でも判定が変わる)。"""
        short_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=dt.timedelta(days=10))
        check.equal(make_service().deprovision(short_id, grace_period=dt.timedelta(days=7)).tenant.status, "DELETED")
        long_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=dt.timedelta(days=30))
        with pytest.raises(DeletionGracePeriodNotElapsedError):
            make_service().deprovision(long_id, grace_period=dt.timedelta(days=31))

    def test_missing_request_time_is_treated_as_now(self, cp_db, make_service, fake_kc):
        """削除要求日時が無い PENDING_DELETION(異常データ)は、猶予期間の起点を『今』とみなして即時には削除しない。"""
        tenant_id = cp_db.insert_tenant(status="PENDING_DELETION")
        with pytest.raises(DeletionGracePeriodNotElapsedError):
            make_service().deprovision(tenant_id)


class TestDeprovisionSuccess:
    """物理削除の正常系。"""

    def test_pending_to_deleted(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """PENDING_DELETION → DEPROVISIONING → DELETED。AP データ削除 → レルム削除の順で、台帳の行は残し、deleted_at を記録する。"""
        tenant_id, realm = pending_tenant(cp_db, fake_kc, clock)
        order = []
        fake_app_data.hook = lambda tid: order.append(("purge", tid))
        fake_kc.hooks["delete_realm_if_exists"] = lambda kwargs: order.append(("delete_realm", kwargs["realm_name"]))
        result = make_service().deprovision(tenant_id, request_id="req-d")
        check.equal(order, [("purge", tenant_id), ("delete_realm", realm)], "AP データ → レルムの順")
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], row["deleted_at"]), ("DELETED", 5, clock.now))
        check.equal(row["updated_by"], "system")
        check.is_not_in(realm, fake_kc.realms)
        check.equal((result.tenant.status, result.purged_rows, result.realm_deleted), ("DELETED", {"t_todo": 3, "t_user": 2}, True))

    def test_history_and_audit(self, cp_db, make_service, fake_kc, clock):
        """履歴は offboard / SUCCEEDED(最終ステップ mark_deleted)、監査ログは deprovision_start → delete(削除件数・レルム削除有無つき)。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        result = make_service().deprovision(tenant_id, request_id="req-d")
        history = cp_db.histories(tenant_id)
        check.equal(len(history), 1)
        check.equal((history[0]["type"], history[0]["status"], history[0]["step"], history[0]["error"], history[0]["id"]), ("offboard", "SUCCEEDED", "mark_deleted", None, result.history_id))
        audits = cp_db.audits(tenant_id)
        check.equal([a["action"] for a in audits], ["tenant.deprovision_start", "tenant.delete"])
        check.is_true(all(a["actor"] == "system" and a["request_id"] == "req-d" for a in audits))
        check.equal(audits[0]["payload"]["status"], {"before": "PENDING_DELETION", "after": "DEPROVISIONING"})
        check.equal(audits[1]["payload"]["status"], {"before": "DEPROVISIONING", "after": "DELETED"})
        check.equal((audits[1]["payload"]["purged_rows"], audits[1]["payload"]["realm_deleted"]), ({"t_todo": 3, "t_user": 2}, True))

    def test_realm_already_gone_is_ok(self, cp_db, make_service, fake_kc, clock):
        """レルムが既に無くても成功する(realm_deleted=False)。再実行できる。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock, realm_exists=False)
        result = make_service().deprovision(tenant_id)
        check.equal((result.tenant.status, result.realm_deleted), ("DELETED", False))

    def test_deleted_code_cannot_be_reused(self, cp_db, make_service, fake_kc, clock):
        """削除後も台帳の行は残り、同じテナントコードでの作成は拒否される(再利用しない。CP-OPS-09)。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        make_service().deprovision(tenant_id)
        check.is_not_none(cp_db.tenant(tenant_id))
        with pytest.raises(TenantCodeAlreadyExistsError):
            make_service().onboard(tenant_code=code, name="Again", initial_admin=initial_admin(), actor="cp-admin")

    def test_custom_actor(self, cp_db, make_service, fake_kc, clock):
        """操作者を指定した場合はその値が更新者・監査ログの actor になる。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        make_service().deprovision(tenant_id, actor="ops-user")
        check.equal(cp_db.tenant(tenant_id)["updated_by"], "ops-user")
        check.is_true(all(a["actor"] == "ops-user" for a in cp_db.audits(tenant_id)))


class TestDeprovisionFailure:
    """失敗時は DEPROVISIONING のまま残し、次回の再試行で収束する。"""

    def test_purge_failure(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """AP データの削除に失敗したら DeprovisioningFailedError。DEPROVISIONING のまま、レルムは削除しない。"""
        tenant_id, realm = pending_tenant(cp_db, fake_kc, clock)
        fake_app_data.errors.append(RuntimeError("db password=LEAK-ME"))
        with pytest.raises(DeprovisioningFailedError) as exc_info:
            make_service().deprovision(tenant_id)
        check.equal((exc_info.value.step, exc_info.value.error_summary), ("purge_app_data", "step=purge_app_data; error=RuntimeError"))
        check.equal(fake_kc.calls, [], "AP データの削除が先なので、レルムは触らない")
        check.is_in(realm, fake_kc.realms)
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["deleted_at"]), ("DEPROVISIONING", None))
        history = cp_db.histories(tenant_id)[0]
        check.equal((history["status"], history["step"], history["error"]), ("FAILED", "purge_app_data", "step=purge_app_data; error=RuntimeError"))
        check.equal(cp_db.audit_actions(tenant_id), ["tenant.deprovision_start", "tenant.deprovision_fail"])
        check.is_not_in("LEAK-ME", cp_db.dump_text(tenant_id))
        check.is_not_in("LEAK-ME", str(exc_info.value))

    def test_realm_deletion_failure(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """レルム削除に失敗したら DeprovisioningFailedError(step=delete_realm)。AP データは削除済みで、DEPROVISIONING のまま。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        fake_kc.fail_once("delete_realm_if_exists", KeycloakAdminError("delete realm", 500, "errorMessage=KC-DETAIL"))
        with pytest.raises(DeprovisioningFailedError) as exc_info:
            make_service().deprovision(tenant_id)
        check.equal(exc_info.value.error_summary, "step=delete_realm; error=KeycloakAdminError; http_status=500")
        check.equal(fake_app_data.calls, [tenant_id])
        check.equal(cp_db.tenant(tenant_id)["status"], "DEPROVISIONING")
        check.is_not_in("KC-DETAIL", cp_db.dump_text(tenant_id))

    def test_retry_after_failure_converges(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """失敗後の再実行(DEPROVISIONING からの再試行)で DELETED に収束する。猶予期間は再確認せず、開始の監査ログは重複しない。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        fake_app_data.errors.append(RuntimeError("down"))
        with pytest.raises(DeprovisioningFailedError):
            make_service().deprovision(tenant_id)
        result = make_service().deprovision(tenant_id)
        check.equal(result.tenant.status, "DELETED")
        check.equal(cp_db.audit_actions(tenant_id), ["tenant.deprovision_start", "tenant.deprovision_fail", "tenant.delete"])
        check.equal([(h["type"], h["status"]) for h in cp_db.histories(tenant_id)], [("offboard", "FAILED"), ("offboard", "SUCCEEDED")])
        check.equal(fake_app_data.calls, [tenant_id, tenant_id], "AP データの削除は冪等な再実行")

    def test_interrupted_running_history_is_closed(self, cp_db, make_service, fake_kc, clock):
        """プロセス停止で RUNNING のまま残った offboard 履歴は、再試行時に閉じる。"""
        tenant_id = cp_db.insert_tenant(status="DEPROVISIONING", version=4)
        fake_kc.realms[cp_db.tenant(tenant_id)["realm_name"]] = False
        from sqlalchemy import text

        with cp_db.runtime.begin() as connection:
            connection.execute(text("INSERT INTO t_provisioning_history (tenant_id, type, status, step, started_at) VALUES (:id, 'offboard', 'RUNNING', 'purge_app_data', :t)"), {"id": tenant_id, "t": clock.now - dt.timedelta(hours=1)})
        make_service().deprovision(tenant_id)
        histories = cp_db.histories(tenant_id)
        check.equal(sorted(h["status"] for h in histories), ["FAILED", "SUCCEEDED"])
        interrupted = next(h for h in histories if h["status"] == "FAILED")
        check.equal(interrupted["error"], "step=purge_app_data; error=interrupted")

    def test_failure_does_not_change_version_or_status_beyond_deprovisioning(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """失敗しても、状態は DEPROVISIONING のまま(FAILED などにしない)。バージョンは開始時の +1 のみ。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        fake_app_data.errors.append(RuntimeError("x"))
        with pytest.raises(DeprovisioningFailedError):
            make_service().deprovision(tenant_id)
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), ("DEPROVISIONING", 4))


class TestDeprovisionGuards:
    """そのほかの拒否。"""

    def test_unknown_tenant(self, make_service):
        """存在しないテナントは TenantNotFoundError。"""
        with pytest.raises(TenantNotFoundError):
            make_service().deprovision(uuid.uuid4())

    def test_operation_in_progress(self, cp_db, make_service, fake_kc, fake_app_data, clock):
        """同じテナントの処理が実行中なら TenantOperationInProgressError。何も削除しない。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        with PgAdvisoryLock(cp_db.runtime).try_acquire(tenant_lock_key(code)) as acquired:
            check.is_true(acquired)
            with pytest.raises(TenantOperationInProgressError):
                make_service().deprovision(tenant_id)
        check.equal((fake_kc.calls, fake_app_data.calls), ([], []))
        check.equal(cp_db.tenant(tenant_id)["status"], "PENDING_DELETION")

    def test_actor_must_not_be_empty(self, cp_db, make_service, fake_kc, clock):
        """操作者が空なら TenantValidationError。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock)
        with pytest.raises(TenantValidationError):
            make_service().deprovision(tenant_id, actor=" ")

    def test_no_audit_for_unreached_steps_on_rejection(self, cp_db, make_service, fake_kc, clock):
        """猶予期間の拒否では deprovision_start の監査ログも残さない。"""
        tenant_id, _ = pending_tenant(cp_db, fake_kc, clock, requested_ago=dt.timedelta(days=1))
        with pytest.raises(DeletionGracePeriodNotElapsedError):
            make_service().deprovision(tenant_id)
        check.equal(cp_db.audits(tenant_id), [])
