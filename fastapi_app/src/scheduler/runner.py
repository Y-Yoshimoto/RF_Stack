#!/usr/bin/env python
# coding:utf-8
"""APScheduler の生成・起動・停止とジョブの登録（02 §5.5）。

方式:
    FastAPI のプロセス内で ``BackgroundScheduler``（スレッド）を動かす。ジョブ本体は同期の DB 処理のため、
    イベントループではなくスレッドプールで実行する。``app.py`` の lifespan から :func:`scheduler_lifespan` を使う。
    ``python -m scheduler`` で同じ定義を ``BlockingScheduler`` として別プロセスでも動かせる。

有効/無効（環境変数 ``SCHEDULER_ENABLED``）:
    - ``true`` / ``1`` / ``yes`` / ``on``: 有効、``false`` / ``0`` / ``no`` / ``off``: 無効（大文字小文字を区別しない）
    - 未設定・空: ``APP_ENV=development`` なら **無効**、それ以外は **有効**
      （開発環境ではバックグラウンドで DB に書き込まない。本番で設定漏れによりジョブが止まらないようにする）
    - それ以外の値は起動時に ``ValueError``

二重実行:
    複数のプロセス・ワーカーで有効にしても、ジョブ本体が CP DB の advisory lock（ジョブ名）を取るため同時には実行されない
    （取れなかった側は ``SKIPPED`` を記録する）。同じプロセス内では ``max_instances=1`` で重ならない。
"""
import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from scheduler.schedule import SCHEDULED_JOBS, ScheduledJob

logger = logging.getLogger(__name__)

SCHEDULER_ENABLED_ENV = "SCHEDULER_ENABLED"

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


def is_scheduler_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """スケジューラを有効にするかを環境変数から判定する。

    Args:
        environ: 環境変数（省略時は ``os.environ``）。

    Returns:
        bool: 有効なら ``True``。

    Raises:
        ValueError: ``SCHEDULER_ENABLED`` が真偽値として解釈できない場合。
    """
    env = os.environ if environ is None else environ
    raw = env.get(SCHEDULER_ENABLED_ENV, "").strip().lower()
    if not raw:
        return env.get("APP_ENV", "").strip().lower() != "development"
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise ValueError(f"{SCHEDULER_ENABLED_ENV} must be one of true/false/1/0/yes/no/on/off: {raw!r}")


def _run_job(job: ScheduledJob) -> None:
    """ジョブ本体を実行し、結果をログに残す（例外はスケジューラに伝えずログに出す）。

    Args:
        job: 実行するジョブ。
    """
    try:
        result = job.func()
    except Exception:
        # セッションの作成・ロックの取得など、ジョブ本体の外側の失敗（DB に接続できない等）
        logger.exception("定期ジョブ %s を実行できませんでした", job.name)
        return
    if result.error:
        logger.warning("定期ジョブ %s: status=%s run_id=%s error=%s", job.name, result.status, result.run_id, result.error)
    else:
        logger.info("定期ジョブ %s: status=%s run_id=%s", job.name, result.status, result.run_id)


def register_jobs(scheduler: BaseScheduler, jobs: Sequence[ScheduledJob] = SCHEDULED_JOBS) -> None:
    """ジョブをスケジューラに登録する。

    Args:
        scheduler: 登録先（起動前）。
        jobs: 登録するジョブ（省略時は :data:`scheduler.schedule.SCHEDULED_JOBS`）。
    """
    for job in jobs:
        scheduler.add_job(
            _run_job,
            trigger=job.trigger(),
            args=[job],
            id=job.name,
            name=job.name,
            misfire_grace_time=job.misfire_grace_time,
            replace_existing=True,
        )


def create_scheduler(jobs: Sequence[ScheduledJob] = SCHEDULED_JOBS, *, blocking: bool = False) -> BaseScheduler:
    """ジョブを登録したスケジューラを生成する（起動はしない）。

    Args:
        jobs: 登録するジョブ。
        blocking: ``True`` なら ``BlockingScheduler``（別プロセス用）、``False`` なら ``BackgroundScheduler``。

    Returns:
        BaseScheduler: スケジューラ。
    """
    options = {
        "timezone": UTC,
        # 遅れた実行はまとめて 1 回にし、同じジョブを同じプロセスで重ねて実行しない
        "job_defaults": {"coalesce": True, "max_instances": 1},
    }
    scheduler: BaseScheduler = BlockingScheduler(**options) if blocking else BackgroundScheduler(**options)
    register_jobs(scheduler, jobs)
    return scheduler


@contextmanager
def scheduler_lifespan(environ: Mapping[str, str] | None = None) -> Iterator[BaseScheduler | None]:
    """有効ならバックグラウンドでスケジューラを起動し、ブロックを抜けると停止する（FastAPI の lifespan 用）。

    停止時は実行中のジョブの終了を待たない（ジョブは冪等で、中断しても次回の実行で回復する）。

    Args:
        environ: 環境変数（省略時は ``os.environ``）。

    Yields:
        BaseScheduler | None: 起動したスケジューラ。無効なら ``None``。

    Raises:
        ValueError: ``SCHEDULER_ENABLED`` が不正な場合。
    """
    if not is_scheduler_enabled(environ):
        logger.info("スケジューラは無効です（%s）", SCHEDULER_ENABLED_ENV)
        yield None
        return
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("スケジューラを起動しました: jobs=%s", [job.id for job in scheduler.get_jobs()])
    try:
        yield scheduler
    finally:
        scheduler.shutdown(wait=False)
        logger.info("スケジューラを停止しました")
