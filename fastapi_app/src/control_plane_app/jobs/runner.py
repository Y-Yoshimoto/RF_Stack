#!/usr/bin/env python
# coding:utf-8
"""定期ジョブの共通の実行処理（二重実行防止と実行履歴の記録。01 §12.1、02 §5.5）。

スケジューラ（APScheduler）にも FastAPI にも依存しない。
"""
import datetime as dt
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from control_plane_app.models.sql_models import RunStatus, TScheduledJobRun
from control_plane_app.repositories.locks import OperationLock, PgAdvisoryLock
from control_plane_app.services.tenant_provisioning import engine_of, utcnow

logger = logging.getLogger(__name__)

# ロックを取得できずにスキップした実行の error 列
LOCK_NOT_ACQUIRED = "lock_not_acquired"


@dataclass(frozen=True, kw_only=True)
class JobOutcome:
    """ジョブ本体の結果。

    Attributes:
        detail: 結果の詳細（ログ・CLI の表示用。DB には保存しない）。
        error: 一部が失敗した場合の要約（秘匿値を含めない）。``None`` なら成功。
    """

    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, kw_only=True)
class JobRunResult:
    """ジョブ 1 回の実行結果。

    Attributes:
        job_name: ジョブ名。
        status: ``SUCCEEDED`` / ``FAILED`` / ``SKIPPED``（ロックを取得できなかった）。
        run_id: ``t_scheduled_job_run`` の ID。
        detail: ジョブ本体の結果の詳細。
        error: 失敗の要約。
    """

    job_name: str
    status: RunStatus
    run_id: uuid.UUID
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def default_session_factory() -> Session:
    """``cp_runtime`` のセッションを作る（providers は FastAPI を import するため遅延 import する）。

    Returns:
        Session: CP DB のセッション。
    """
    from modules.tenancy.providers import get_cp_sessionmaker

    return get_cp_sessionmaker()()


def run_scheduled_job(
    job_name: str,
    body: Callable[[Session], JobOutcome],
    *,
    session_factory: Callable[[], Session] | None = None,
    lock: OperationLock | None = None,
    clock: Callable[[], dt.datetime] = utcnow,
) -> JobRunResult:
    """ジョブ本体を、二重実行防止と実行履歴の記録付きで実行する。

    1. CP DB の advisory lock（``hashtext(job_name)``）を取得する。取れなければ ``SKIPPED`` を記録して返す
    2. ``t_scheduled_job_run`` に ``RUNNING`` をコミットする
    3. ``body(session)`` を実行する（本体がコミットする）
    4. ``SUCCEEDED`` / ``FAILED`` と終了日時をコミットする（本体の例外は送出せず ``FAILED`` として返す）

    Args:
        job_name: ジョブ名（ロックキーと ``t_scheduled_job_run.job_name``）。
        body: ジョブ本体。CP DB のセッションを受け取る。
        session_factory: CP DB のセッションを作る関数（省略時は ``cp_runtime``）。
        lock: 排他ロック（省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。

    Returns:
        JobRunResult: 実行結果。
    """
    factory = session_factory or default_session_factory
    with factory() as session:
        job_lock = lock or PgAdvisoryLock(engine_of(session))
        with job_lock.try_acquire(job_name) as acquired:
            started_at = clock()
            if not acquired:
                run = TScheduledJobRun(job_name=job_name, status=RunStatus.SKIPPED.value, started_at=started_at, finished_at=started_at, error=LOCK_NOT_ACQUIRED)
                session.add(run)
                run_id = run.id
                session.commit()
                logger.info("ジョブ %s は他で実行中のためスキップしました", job_name)
                return JobRunResult(job_name=job_name, status=RunStatus.SKIPPED, run_id=run_id, error=LOCK_NOT_ACQUIRED)

            run = TScheduledJobRun(job_name=job_name, status=RunStatus.RUNNING.value, started_at=started_at)
            session.add(run)
            run_id = run.id
            session.commit()

            try:
                outcome = body(session)
            except Exception as exc:
                session.rollback()
                logger.exception("ジョブ %s が失敗しました", job_name)
                outcome = JobOutcome(error=f"error={type(exc).__name__}")

            status = RunStatus.FAILED if outcome.error else RunStatus.SUCCEEDED
            record = session.get(TScheduledJobRun, run_id)
            if record is not None:
                record.status = status.value
                record.finished_at = clock()
                record.error = outcome.error
                session.commit()
            logger.info("ジョブ %s を終了しました: status=%s", job_name, status)
            return JobRunResult(job_name=job_name, status=status, run_id=run_id, detail=outcome.detail, error=outcome.error)
