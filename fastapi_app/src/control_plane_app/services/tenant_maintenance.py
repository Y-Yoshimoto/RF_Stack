#!/usr/bin/env python
# coding:utf-8
"""定期ジョブから呼ぶテナントの保守処理（Keycloak を使わない部分）。FastAPI・スケジューラに依存しない。

- :func:`reap_stale_provisioning` — 一定時間（既定 10 分）以上 ``PROVISIONING`` のままの払い出しを ``FAILED`` にする（01 CP-ONB-09）
- :func:`list_deprovisionable_tenant_ids` — 物理削除の対象（猶予期間を過ぎた ``PENDING_DELETION`` と、前回失敗した ``DEPROVISIONING``）を返す

物理削除そのものは :meth:`control_plane_app.services.tenant_provisioning.TenantProvisioningService.deprovision`。
ジョブとしての実行（二重実行防止・実行履歴）は :mod:`control_plane_app.jobs`。
"""
import datetime as dt
import logging
import uuid
from collections.abc import Callable

from sqlmodel import Session

from control_plane_app.models.sql_models import ProvisioningType, TenantStatus
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.repositories.locks import OperationLock, PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.tenant_lifecycle import DELETION_GRACE_PERIOD, STALE_PROVISIONING_THRESHOLD
from control_plane_app.services.tenant_provisioning import SYSTEM_ACTOR, AuditAction, bump_version, engine_of, status_change_payload, utcnow

logger = logging.getLogger(__name__)

# 回収した払い出し履歴に記録するエラー種別
REAPED_ERROR = "interrupted (provisioning_reaper)"


def reap_stale_provisioning(
    session: Session,
    *,
    threshold: dt.timedelta = STALE_PROVISIONING_THRESHOLD,
    actor: str = SYSTEM_ACTOR,
    lock: OperationLock | None = None,
    clock: Callable[[], dt.datetime] = utcnow,
) -> list[uuid.UUID]:
    """``threshold`` 以上 ``PROVISIONING`` のままのテナントを ``FAILED`` にする（01 CP-ONB-09）。

    テナント単位のロックが取れないもの（払い出しが実行中）は対象外とする。対象テナントごとに
    台帳 ``FAILED``・``RUNNING`` の払い出し履歴を ``FAILED``・監査ログ ``tenant.provision_reap`` をコミットする。
    ``FAILED`` にしたテナントは :meth:`~control_plane_app.services.tenant_provisioning.TenantProvisioningService.retry` で再実行できる。

    Args:
        session: CP DB（``cp_runtime``）のセッション。関数内でコミットする。
        threshold: 中断とみなすまでの時間（``updated_at`` からの経過）。
        actor: 操作者（既定 ``system``）。
        lock: テナント単位の排他ロック（省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。

    Returns:
        list[uuid.UUID]: ``FAILED`` にしたテナント ID。
    """
    lock = lock or PgAdvisoryLock(engine_of(session))
    now = clock()
    cutoff = now - threshold
    candidates = [(tenant.id, tenant.tenant_code) for tenant in repo.list_tenants_by_status_updated_before(session, TenantStatus.PROVISIONING.value, cutoff)]
    session.rollback()

    reaped: list[uuid.UUID] = []
    for tenant_id, tenant_code in candidates:
        with lock.try_acquire(tenant_lock_key(tenant_code)) as acquired:
            if not acquired:
                logger.info("払い出しが実行中のため回収しません: tenant_id=%s", tenant_id)
                continue
            tenant = repo.get_tenant(session, tenant_id, for_update=True)
            if tenant is None or tenant.status != TenantStatus.PROVISIONING or tenant.updated_at >= cutoff:
                session.rollback()
                continue
            before_version = tenant.version
            tenant.status = TenantStatus.FAILED.value
            bump_version(tenant, actor)
            closed = repo.close_running_histories(session, tenant_id, ProvisioningType.ONBOARD, REAPED_ERROR, now)
            repo.add_cp_audit_log(
                session, actor=actor, action=AuditAction.PROVISION_REAP, tenant_id=tenant_id,
                payload={**status_change_payload(TenantStatus.PROVISIONING.value, tenant.status, before_version, tenant.version), "closed_histories": closed},
            )
            session.commit()
            reaped.append(tenant_id)
            logger.warning("中断した払い出しを FAILED にしました: tenant_id=%s", tenant_id)
    return reaped


def list_deprovisionable_tenant_ids(session: Session, *, grace_period: dt.timedelta = DELETION_GRACE_PERIOD, clock: Callable[[], dt.datetime] = utcnow) -> list[uuid.UUID]:
    """物理削除の対象テナントの ID を返す（01 CP-OPS-08）。

    対象は、削除要求から ``grace_period`` 以上経過した ``PENDING_DELETION`` と、前回の物理削除が失敗した
    ``DEPROVISIONING``。読み取りのトランザクションは閉じて返す。

    Args:
        session: CP DB のセッション。
        grace_period: 猶予期間（既定 30 日）。
        clock: 現在時刻（UTC）を返す関数。

    Returns:
        list[uuid.UUID]: 対象テナント ID（削除要求日時の昇順）。
    """
    requested_before = clock() - grace_period
    tenants = repo.list_tenants_for_deprovisioning(session, TenantStatus.PENDING_DELETION.value, TenantStatus.DEPROVISIONING.value, requested_before)
    tenant_ids = [tenant.id for tenant in tenants]
    session.rollback()
    return tenant_ids
