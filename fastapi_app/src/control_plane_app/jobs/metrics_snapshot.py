#!/usr/bin/env python
# coding:utf-8
"""定期ジョブ ``metrics_snapshot``（日次）: テナント毎のメトリクスを日次メトリクスに保存する（01 CP-MET-01/02/05）。

対象テナント:
    ``ACTIVE`` と ``SUSPENDED``（:data:`METRICS_TARGET_STATUSES`）。停止中もデータは残り、再開まで推移を途切れさせないため含める。
    ``PROVISIONING`` / ``FAILED``（払い出し未完了）、``PENDING_DELETION`` / ``DEPROVISIONING`` / ``DELETED``（削除に向かう）は対象外。

集計対象日:
    実行時点の **UTC の当日**（``clock().date()``）。値は「その日に取得した時点の状態」を表す。
    同じ日に再実行すると同じキーの行を上書きする（``ON CONFLICT ... DO UPDATE``。行数は変わらない）。
    前日にしない理由: 指標は過去に遡って求められない現在の状態のスナップショットであり、日中に CLI で実行した値を
    前日の行に書くと前日の値が壊れるため。スケジューラは UTC の 1 日の終わり近く（``scheduler/schedule.py``）に実行する。

1 テナントの集計・保存に失敗しても他のテナントは処理を続け、ジョブは ``FAILED`` になる（次回の実行で上書きされる）。
"""
import datetime as dt
import logging
from collections.abc import Callable
from decimal import Decimal

from sqlmodel import Session

from control_plane_app.jobs.runner import JobOutcome, JobRunResult, run_scheduled_job
from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.repositories.app_tenant_metrics import AppTenantMetricsRepository
from control_plane_app.repositories.daily_metric_repository import upsert_daily_metrics
from control_plane_app.repositories.locks import OperationLock
from control_plane_app.services.tenant_provisioning import utcnow

logger = logging.getLogger(__name__)

JOB_NAME = "metrics_snapshot"

# 日次メトリクスを取るテナントの状態
METRICS_TARGET_STATUSES: tuple[TenantStatus, ...] = (TenantStatus.ACTIVE, TenantStatus.SUSPENDED)


def run_metrics_snapshot(
    *,
    session_factory: Callable[[], Session] | None = None,
    metrics: AppTenantMetricsRepository | None = None,
    lock: OperationLock | None = None,
    clock: Callable[[], dt.datetime] = utcnow,
) -> JobRunResult:
    """対象テナントの指標を AP DB から集計し、``t_tenant_daily_metric`` に UPSERT する。

    Args:
        session_factory: CP DB のセッションを作る関数（省略時は ``cp_runtime``）。
        metrics: AP DB の集計（省略時は ``app_cp_agent`` と、基盤 + 登録済みテーマの指標セット）。
        lock: ジョブの排他ロック（省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。集計対象日はこの UTC の日付。

    Returns:
        JobRunResult: 実行結果（``detail`` に ``date`` / ``tenants`` / ``rows_changed`` / ``failed``）。
        1 テナントでも失敗したら ``FAILED``。
    """

    def body(session: Session) -> JobOutcome:
        """対象テナントを順に集計・保存する（テナント毎にコミットする）。"""
        snapshot_date = clock().astimezone(dt.UTC).date()
        collector = metrics or AppTenantMetricsRepository()
        tenant_ids = repo.list_tenant_ids_by_statuses(session, [status.value for status in METRICS_TARGET_STATUSES])
        session.rollback()

        succeeded: list[str] = []
        failed: dict[str, str] = {}
        rows_changed = 0
        for tenant_id in tenant_ids:
            try:
                values: dict[str, Decimal] = collector.collect_tenant_metrics(tenant_id)
                rows_changed += upsert_daily_metrics(session, tenant_id, snapshot_date, values)
                session.commit()
                succeeded.append(str(tenant_id))
            except Exception as exc:
                session.rollback()
                logger.exception("テナントのメトリクスの集計・保存に失敗しました: tenant_id=%s", tenant_id)
                failed[str(tenant_id)] = type(exc).__name__
        error = None
        if failed:
            error = f"{len(failed)} tenant(s) failed: " + ", ".join(f"{tenant_id}={code}" for tenant_id, code in failed.items())
        detail = {"date": snapshot_date.isoformat(), "metric_keys": collector.metric_keys, "tenants": succeeded, "rows_changed": rows_changed, "failed": failed}
        return JobOutcome(detail=detail, error=error)

    return run_scheduled_job(JOB_NAME, body, session_factory=session_factory, lock=lock, clock=clock)
