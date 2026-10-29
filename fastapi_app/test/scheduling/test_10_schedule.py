# -*- coding: utf-8 -*-
"""scheduler.schedule.SCHEDULED_JOBS(ジョブと周期の定義。01 §12.1)と、scheduler.runner の登録・実行ラッパーのテスト。

実際のジョブ本体は実行しない(DB・Keycloak には接続しない)。周期は APScheduler のトリガーから次の実行時刻を計算して確認する。
"""
import dataclasses
import datetime as dt
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import pytest_check as check
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from control_plane_app.jobs.metrics_snapshot import JOB_NAME as METRICS_SNAPSHOT
from control_plane_app.jobs.metrics_snapshot import run_metrics_snapshot
from control_plane_app.jobs.provisioning_reaper import JOB_NAME as PROVISIONING_REAPER
from control_plane_app.jobs.provisioning_reaper import run_provisioning_reaper
from control_plane_app.jobs.runner import JobRunResult
from control_plane_app.jobs.tenant_purge import JOB_NAME as TENANT_PURGE
from control_plane_app.jobs.tenant_purge import run_tenant_purge
from control_plane_app.models.sql_models import RunStatus
from scheduler import runner
from scheduler.schedule import SCHEDULED_JOBS, ScheduledJob

NOON = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC)


def job_named(name: str) -> ScheduledJob:
    return next(job for job in SCHEDULED_JOBS if job.name == name)


def next_fire(trigger, now, previous=None):
    return trigger.get_next_fire_time(previous, now)


class TestDefinitions:
    """ジョブの一覧と、ジョブ本体との対応。"""

    def test_three_jobs_with_unique_names(self):
        """定期ジョブは metrics_snapshot / tenant_purge / provisioning_reaper の 3 つで、名前は重複しない。"""
        names = [job.name for job in SCHEDULED_JOBS]
        check.equal(sorted(names), sorted([METRICS_SNAPSHOT, TENANT_PURGE, PROVISIONING_REAPER]))
        check.equal(sorted(names), ["metrics_snapshot", "provisioning_reaper", "tenant_purge"])
        check.equal(len(set(names)), len(names))

    def test_functions_are_the_job_bodies(self):
        """各ジョブの実行関数は、control_plane_app/jobs の本体。"""
        check.is_(job_named(METRICS_SNAPSHOT).func, run_metrics_snapshot)
        check.is_(job_named(TENANT_PURGE).func, run_tenant_purge)
        check.is_(job_named(PROVISIONING_REAPER).func, run_provisioning_reaper)

    def test_trigger_factories_return_new_instances(self):
        """トリガーは呼ぶたびに新しいインスタンス(スケジューラの生成ごとに独立)。"""
        for job in SCHEDULED_JOBS:
            check.is_not(job.trigger(), job.trigger())

    def test_job_is_immutable(self):
        """ジョブ定義は不変。"""
        with pytest.raises(dataclasses.FrozenInstanceError):
            SCHEDULED_JOBS[0].name = "x"


class TestPeriods:
    """周期(01 §12.1 の表)。時刻はすべて UTC。"""

    def test_metrics_snapshot_runs_daily_at_2345_utc(self):
        """metrics_snapshot は日次 23:45 UTC。その時刻を過ぎていれば翌日。"""
        trigger = job_named(METRICS_SNAPSHOT).trigger()
        check.is_instance(trigger, CronTrigger)
        check.equal(next_fire(trigger, NOON), dt.datetime(2026, 5, 1, 23, 45, tzinfo=dt.UTC))
        check.equal(next_fire(trigger, dt.datetime(2026, 5, 1, 23, 46, tzinfo=dt.UTC)), dt.datetime(2026, 5, 2, 23, 45, tzinfo=dt.UTC))
        check.equal(next_fire(trigger, dt.datetime(2026, 5, 1, 23, 45, tzinfo=dt.UTC)), dt.datetime(2026, 5, 1, 23, 45, tzinfo=dt.UTC))

    def test_tenant_purge_runs_daily_at_1800_utc(self):
        """tenant_purge は日次 18:00 UTC(日本時間 03:00)。"""
        trigger = job_named(TENANT_PURGE).trigger()
        check.is_instance(trigger, CronTrigger)
        check.equal(next_fire(trigger, NOON), dt.datetime(2026, 5, 1, 18, 0, tzinfo=dt.UTC))
        check.equal(next_fire(trigger, dt.datetime(2026, 5, 1, 18, 1, tzinfo=dt.UTC)), dt.datetime(2026, 5, 2, 18, 0, tzinfo=dt.UTC))
        jst = dt.timezone(dt.timedelta(hours=9))
        check.equal(next_fire(trigger, NOON).astimezone(jst).hour, 3)

    def test_provisioning_reaper_runs_every_10_minutes(self):
        """provisioning_reaper は 10 分間隔(中断判定のしきい値 10 分と同じ)。前回の実行から 10 分後。"""
        trigger = job_named(PROVISIONING_REAPER).trigger()
        check.is_instance(trigger, IntervalTrigger)
        check.equal(trigger.interval, dt.timedelta(minutes=10))
        previous = dt.datetime(2026, 5, 1, 12, 10, tzinfo=dt.UTC)
        check.equal(next_fire(trigger, previous + dt.timedelta(seconds=1), previous), previous + dt.timedelta(minutes=10))

    @pytest.mark.parametrize("name", [METRICS_SNAPSHOT, TENANT_PURGE, PROVISIONING_REAPER])
    def test_triggers_use_utc(self, name):
        """どのトリガーも UTC で計算する(サーバーのタイムゾーンに依存しない)。"""
        check.equal(job_named(name).trigger().timezone, dt.UTC)

    def test_metrics_snapshot_misfire_grace_stays_within_the_day(self):
        """metrics_snapshot の許容遅れは、予定時刻 + 許容遅れが 24:00 を超えない(日付が変わってから実行すると翌日の行になるため)。"""
        job = job_named(METRICS_SNAPSHOT)
        deadline = dt.datetime(2026, 5, 1, 23, 45, tzinfo=dt.UTC) + dt.timedelta(seconds=job.misfire_grace_time)
        check.less(deadline, dt.datetime(2026, 5, 2, 0, 0, tzinfo=dt.UTC))
        check.equal(job.misfire_grace_time, 600)

    def test_other_misfire_graces(self):
        """tenant_purge は 6 時間、provisioning_reaper は 5 分(次の実行より短い)まで遅れても実行する。"""
        check.equal(job_named(TENANT_PURGE).misfire_grace_time, 6 * 60 * 60)
        reaper = job_named(PROVISIONING_REAPER)
        check.equal(reaper.misfire_grace_time, 5 * 60)
        check.less(reaper.misfire_grace_time, reaper.trigger().interval.total_seconds())


@contextmanager
def paused(scheduler) -> Iterator:
    """スケジューラを一時停止状態で起動する(ジョブは登録されるが、実行されない)。終了時に停止する。"""
    scheduler.start(paused=True)
    try:
        yield scheduler
    finally:
        scheduler.shutdown(wait=False)


class TestCreateScheduler:
    """ジョブを登録したスケジューラの生成(起動はしない)。"""

    def test_background_by_default_and_not_started(self):
        """既定は BackgroundScheduler。生成しただけでは起動しない。ジョブはジョブ名の ID で 3 つ登録される。"""
        scheduler = runner.create_scheduler()
        check.is_instance(scheduler, BackgroundScheduler)
        check.is_false(scheduler.running)
        check.equal(sorted(job.id for job in scheduler.get_jobs()), sorted(job.name for job in SCHEDULED_JOBS))

    def test_blocking_for_separate_process(self):
        """blocking=True なら別プロセス用の BlockingScheduler。"""
        check.is_instance(runner.create_scheduler(blocking=True), BlockingScheduler)

    def test_job_options(self):
        """遅れた実行はまとめて 1 回(coalesce)、同じジョブは同時に 1 つ(max_instances=1)。許容遅れ・タイムゾーンは定義どおり。次の実行は未来の時刻。"""
        now = dt.datetime.now(dt.UTC)
        with paused(runner.create_scheduler()) as scheduler:
            check.equal(scheduler.timezone, dt.UTC)
            registered_jobs = scheduler.get_jobs()
            check.equal(len(registered_jobs), len(SCHEDULED_JOBS))
            for registered in registered_jobs:
                definition = job_named(registered.id)
                check.is_true(registered.coalesce, registered.id)
                check.equal(registered.max_instances, 1, registered.id)
                check.equal(registered.misfire_grace_time, definition.misfire_grace_time, registered.id)
                check.equal(registered.name, definition.name)
                check.greater(registered.next_run_time, now, registered.id)

    def test_register_jobs_is_idempotent(self):
        """同じ定義を 2 回登録しても、起動後のジョブは重複しない(replace_existing)。"""
        scheduler = runner.create_scheduler()
        runner.register_jobs(scheduler)
        with paused(scheduler):
            check.equal(sorted(job.id for job in scheduler.get_jobs()), sorted(job.name for job in SCHEDULED_JOBS))

    def test_custom_jobs(self):
        """ジョブの一覧を引数で渡せる(空ならジョブなし)。"""
        check.equal(runner.create_scheduler(()).get_jobs(), [])
        only = SCHEDULED_JOBS[:1]
        check.equal([job.id for job in runner.create_scheduler(only).get_jobs()], [only[0].name])


class TestRunJobWrapper:
    """スケジューラが呼ぶラッパー(結果のログ。例外はスケジューラに伝えない)。"""

    @staticmethod
    def job(func):
        return ScheduledJob(name="probe", func=func, trigger=lambda: IntervalTrigger(hours=1), misfire_grace_time=1)

    @staticmethod
    def result(status=RunStatus.SUCCEEDED, error=None):
        return JobRunResult(job_name="probe", status=status, run_id=uuid.uuid4(), error=error)

    def test_success_is_logged_at_info(self, caplog):
        """成功は info で status と run_id をログに残す。"""
        result = self.result()
        with caplog.at_level(logging.INFO, logger="scheduler.runner"):
            runner._run_job(self.job(lambda: result))
        records = [r for r in caplog.records if r.name == "scheduler.runner"]
        check.equal([r.levelno for r in records], [logging.INFO])
        check.is_in(str(result.run_id), records[0].getMessage())

    def test_job_error_is_logged_as_warning(self, caplog):
        """ジョブが error 付きで終わった(FAILED 等)場合は warning でエラーの要約を残す。"""
        result = self.result(RunStatus.FAILED, "1 tenant(s) failed")
        with caplog.at_level(logging.INFO, logger="scheduler.runner"):
            runner._run_job(self.job(lambda: result))
        records = [r for r in caplog.records if r.name == "scheduler.runner"]
        check.equal([r.levelno for r in records], [logging.WARNING])
        check.is_in("1 tenant(s) failed", records[0].getMessage())

    def test_exception_is_logged_and_not_raised(self, caplog):
        """ジョブ本体の外側の例外(DB に接続できない等)は、スケジューラに伝えず exception ログに残す。"""

        def boom():
            raise ConnectionError("db is down")

        with caplog.at_level(logging.INFO, logger="scheduler.runner"):
            runner._run_job(self.job(boom))
        records = [r for r in caplog.records if r.name == "scheduler.runner"]
        check.equal([r.levelno for r in records], [logging.ERROR])
        check.is_in("probe", records[0].getMessage())
        check.is_not_none(records[0].exc_info)

    def test_registered_wrapper_calls_the_definition(self):
        """スケジューラに登録される実行関数は _run_job で、引数に定義(ScheduledJob)を渡す。"""
        scheduler = runner.create_scheduler(SCHEDULED_JOBS)
        for registered in scheduler.get_jobs():
            check.is_(registered.func, runner._run_job)
            check.equal(registered.args, (job_named(registered.id),))
