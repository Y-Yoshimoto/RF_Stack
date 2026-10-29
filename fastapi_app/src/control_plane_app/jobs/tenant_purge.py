#!/usr/bin/env python
# coding:utf-8
"""定期ジョブ ``tenant_purge``（日次）: 猶予期間を過ぎたテナントの認証領域・データを物理削除する（01 CP-OPS-08）。

テナントごとに管理クライアントを作り直す（締め切り 30 秒は 1 テナントの処理に対して適用する）。
1 テナントの失敗で他のテナントの処理は止めない。失敗したテナントは ``DEPROVISIONING`` のまま残り、次回の実行で再試行される。
"""
import datetime as dt
import logging
from collections.abc import Callable

from sqlmodel import Session

from control_plane_app.jobs.runner import JobOutcome, JobRunResult, run_scheduled_job
from control_plane_app.repositories.app_tenant_data import AppTenantDataRepository
from control_plane_app.repositories.locks import OperationLock
from control_plane_app.services.errors import TenantServiceError
from control_plane_app.services.tenant_lifecycle import DELETION_GRACE_PERIOD
from control_plane_app.services.tenant_maintenance import list_deprovisionable_tenant_ids
from control_plane_app.services.tenant_provisioning import TenantProvisioningService, utcnow
from modules.keycloak_admin.admin_client import KeycloakAdminClient
from modules.keycloak_admin.templates import create_provisioner_admin_client

logger = logging.getLogger(__name__)

JOB_NAME = "tenant_purge"


def run_tenant_purge(
    *,
    session_factory: Callable[[], Session] | None = None,
    admin_factory: Callable[[], KeycloakAdminClient] = create_provisioner_admin_client,
    app_data: AppTenantDataRepository | None = None,
    grace_period: dt.timedelta = DELETION_GRACE_PERIOD,
    lock: OperationLock | None = None,
    clock: Callable[[], dt.datetime] = utcnow,
) -> JobRunResult:
    """猶予期間を過ぎた ``PENDING_DELETION`` と、前回失敗した ``DEPROVISIONING`` のテナントを物理削除する。

    Args:
        session_factory: CP DB のセッションを作る関数（省略時は ``cp_runtime``）。
        admin_factory: Keycloak の管理クライアントを作る関数（テナントごとに呼ぶ）。
        app_data: AP DB のテナントデータの物理削除（省略時は ``app_cp_agent`` の既定の実装）。
        grace_period: 猶予期間（既定 30 日）。
        lock: 排他ロック（ジョブ・テナントの両方に使う。省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。

    Returns:
        JobRunResult: 実行結果（``detail["deleted"]`` / ``detail["failed"]``）。1 テナントでも失敗したら ``FAILED``。
    """

    def body(session: Session) -> JobOutcome:
        """対象テナントを順に物理削除する。"""
        deleted: list[str] = []
        failed: dict[str, str] = {}
        for tenant_id in list_deprovisionable_tenant_ids(session, grace_period=grace_period, clock=clock):
            try:
                with admin_factory() as admin:
                    service = TenantProvisioningService(session, admin, app_data=app_data, lock=lock, clock=clock)
                    service.deprovision(tenant_id, grace_period=grace_period)
                deleted.append(str(tenant_id))
            except TenantServiceError as exc:
                failed[str(tenant_id)] = exc.code
            except Exception as exc:
                session.rollback()
                logger.exception("テナントの物理削除で予期しないエラーが発生しました: tenant_id=%s", tenant_id)
                failed[str(tenant_id)] = type(exc).__name__
        error = None
        if failed:
            error = f"{len(failed)} tenant(s) failed: " + ", ".join(f"{tenant_id}={code}" for tenant_id, code in failed.items())
        return JobOutcome(detail={"deleted": deleted, "failed": failed}, error=error)

    return run_scheduled_job(JOB_NAME, body, session_factory=session_factory, lock=lock, clock=clock)
