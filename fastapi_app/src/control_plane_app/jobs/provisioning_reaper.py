#!/usr/bin/env python
# coding:utf-8
"""定期ジョブ ``provisioning_reaper``（10 分毎）: 長時間 ``PROVISIONING`` の払い出しを ``FAILED`` にする（01 CP-ONB-09）。"""
import datetime as dt
from collections.abc import Callable

from sqlmodel import Session

from control_plane_app.jobs.runner import JobOutcome, JobRunResult, run_scheduled_job
from control_plane_app.repositories.locks import OperationLock
from control_plane_app.services.tenant_lifecycle import STALE_PROVISIONING_THRESHOLD
from control_plane_app.services.tenant_maintenance import reap_stale_provisioning
from control_plane_app.services.tenant_provisioning import utcnow

JOB_NAME = "provisioning_reaper"


def run_provisioning_reaper(
    *,
    session_factory: Callable[[], Session] | None = None,
    threshold: dt.timedelta = STALE_PROVISIONING_THRESHOLD,
    lock: OperationLock | None = None,
    clock: Callable[[], dt.datetime] = utcnow,
) -> JobRunResult:
    """``threshold``（既定 10 分）以上 ``PROVISIONING`` のままのテナントを ``FAILED`` にする。

    Args:
        session_factory: CP DB のセッションを作る関数（省略時は ``cp_runtime``）。
        threshold: 中断とみなすまでの時間。
        lock: 排他ロック（ジョブ・テナントの両方に使う。省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。

    Returns:
        JobRunResult: 実行結果（``detail["reaped"]`` に ``FAILED`` にしたテナント ID）。
    """

    def body(session: Session) -> JobOutcome:
        """回収を実行する。"""
        reaped = reap_stale_provisioning(session, threshold=threshold, lock=lock, clock=clock)
        return JobOutcome(detail={"reaped": [str(tenant_id) for tenant_id in reaped]})

    return run_scheduled_job(JOB_NAME, body, session_factory=session_factory, lock=lock, clock=clock)
