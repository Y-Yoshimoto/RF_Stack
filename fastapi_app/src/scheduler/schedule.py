#!/usr/bin/env python
# coding:utf-8
"""定期ジョブと周期の定義（01 §12.1 の表）。ジョブの追加・周期の変更はここだけで行う。

時刻はすべて UTC。

| ジョブ | 周期 | 備考 |
| --- | --- | --- |
| ``metrics_snapshot`` | 日次 23:45 | 集計対象日は実行時の UTC の当日。1 日の終わり近くに取り、その日の状態を表す値にする |
| ``tenant_purge`` | 日次 18:00 | 日本時間 03:00 の低負荷帯。Keycloak・AP DB の物理削除を伴う |
| ``provisioning_reaper`` | 10 分毎 | 中断判定（10 分）と同じ間隔 |

``misfire_grace_time`` はプロセスの停止・遅延で予定時刻を過ぎた場合に、何秒遅れまでなら実行するか。
過ぎた分はまとめて 1 回だけ実行する（``coalesce``。``scheduler/runner.py`` の既定）。
"""
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from control_plane_app.jobs.metrics_snapshot import JOB_NAME as METRICS_SNAPSHOT
from control_plane_app.jobs.metrics_snapshot import run_metrics_snapshot
from control_plane_app.jobs.provisioning_reaper import JOB_NAME as PROVISIONING_REAPER
from control_plane_app.jobs.provisioning_reaper import run_provisioning_reaper
from control_plane_app.jobs.runner import JobRunResult
from control_plane_app.jobs.tenant_purge import JOB_NAME as TENANT_PURGE
from control_plane_app.jobs.tenant_purge import run_tenant_purge


@dataclass(frozen=True, kw_only=True)
class ScheduledJob:
    """スケジュールに登録するジョブ。

    Attributes:
        name: ジョブ名（APScheduler のジョブ ID。``t_scheduled_job_run.job_name`` と同じ）。
        func: ジョブ本体（引数なし。既定の接続・設定を使う）。
        trigger: 周期を表す APScheduler のトリガーを作る関数（スケジューラの生成毎に新しく作る）。
        misfire_grace_time: 予定時刻からの許容遅れ（秒）。
    """

    name: str
    func: Callable[[], JobRunResult]
    trigger: Callable[[], BaseTrigger]
    misfire_grace_time: int


SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    ScheduledJob(
        name=METRICS_SNAPSHOT,
        func=run_metrics_snapshot,
        trigger=lambda: CronTrigger(hour=23, minute=45, timezone=dt.UTC),
        # 23:55 までに開始できなければ実行しない（日付が変わってから実行すると翌日の行になり、その日の行が欠けたうえ翌日の行を早く埋めるため）
        misfire_grace_time=10 * 60,
    ),
    ScheduledJob(
        name=TENANT_PURGE,
        func=run_tenant_purge,
        trigger=lambda: CronTrigger(hour=18, minute=0, timezone=dt.UTC),
        misfire_grace_time=6 * 60 * 60,
    ),
    ScheduledJob(
        name=PROVISIONING_REAPER,
        func=run_provisioning_reaper,
        trigger=lambda: IntervalTrigger(minutes=10, timezone=dt.UTC),
        misfire_grace_time=5 * 60,
    ),
)
