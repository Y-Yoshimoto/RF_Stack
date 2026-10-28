# -*- coding: utf-8 -*-
"""scheduler.runner.scheduler_lifespan と、アプリ(app.py)の lifespan でのスケジューラの起動・停止のテスト。

**実際のジョブは走らせない**: ジョブ本体を記録するだけの関数に差し替え、トリガーは未来の時刻(実行されない)にする。DB・Keycloak には接続しない。
"""
import dataclasses
import datetime as dt

import pytest
import pytest_check as check
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING, STATE_STOPPED
from fastapi.testclient import TestClient

from app import app
from scheduler import runner
from scheduler.schedule import SCHEDULED_JOBS


class Spy:
    """ジョブ本体の代わり(呼ばれたら記録する)。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def func_for(self, name: str):
        def func():
            self.calls.append(name)
            raise AssertionError("定期ジョブの本体は実行してはならない")

        return func


@pytest.fixture
def spy_jobs(monkeypatch):
    """本物のスケジュール定義(名前・周期)のまま、ジョブ本体だけを記録用の関数に差し替える。生成されたスケジューラを ``created`` に残す。"""
    spy = Spy()
    spy.created = []
    replaced = tuple(dataclasses.replace(job, func=spy.func_for(job.name)) for job in SCHEDULED_JOBS)
    real_create = runner.create_scheduler

    def create(jobs=replaced, *, blocking=False):
        scheduler = real_create(jobs, blocking=blocking)
        spy.created.append(scheduler)
        return scheduler

    monkeypatch.setattr(runner, "create_scheduler", create)
    return spy


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(runner.SCHEDULER_ENABLED_ENV, raising=False)
    monkeypatch.setenv("APP_ENV", "production")


class TestSchedulerLifespan:
    """scheduler_lifespan(有効ならバックグラウンドで起動し、抜けると停止する)。"""

    def test_enabled_starts_and_stops(self, spy_jobs):
        """有効なら BackgroundScheduler を起動して yield し、ブロックを抜けると停止する。ジョブは 3 つ登録されているが、実行されていない。"""
        with runner.scheduler_lifespan({runner.SCHEDULER_ENABLED_ENV: "true"}) as scheduler:
            check.is_instance(scheduler, BackgroundScheduler)
            check.equal(scheduler.state, STATE_RUNNING)
            check.equal(sorted(job.id for job in scheduler.get_jobs()), sorted(job.name for job in SCHEDULED_JOBS))
            check.is_true(all(job.next_run_time > dt.datetime.now(dt.UTC) for job in scheduler.get_jobs()))
        check.equal(scheduler.state, STATE_STOPPED)
        check.equal(spy_jobs.calls, [])

    def test_disabled_yields_none_and_creates_nothing(self, spy_jobs):
        """無効なら None を yield し、スケジューラを作らない。"""
        with runner.scheduler_lifespan({runner.SCHEDULER_ENABLED_ENV: "false"}) as scheduler:
            check.is_none(scheduler)
        check.equal(spy_jobs.created, [])

    def test_development_default_is_disabled(self, spy_jobs):
        """SCHEDULER_ENABLED 未設定で APP_ENV=development なら起動しない(開発環境でバックグラウンドの書き込みをしない)。"""
        with runner.scheduler_lifespan({"APP_ENV": "development"}) as scheduler:
            check.is_none(scheduler)
        check.equal(spy_jobs.created, [])

    def test_production_default_is_enabled(self, spy_jobs):
        """未設定で APP_ENV=production なら起動し、終了時に停止する。"""
        with runner.scheduler_lifespan({"APP_ENV": "production"}) as scheduler:
            check.equal(scheduler.state, STATE_RUNNING)
        check.equal(scheduler.state, STATE_STOPPED)

    def test_invalid_value_raises_before_creating_scheduler(self, spy_jobs):
        """SCHEDULER_ENABLED が不正なら ValueError で、スケジューラを作らない。"""
        with pytest.raises(ValueError), runner.scheduler_lifespan({runner.SCHEDULER_ENABLED_ENV: "maybe"}):
            pass
        check.equal(spy_jobs.created, [])

    def test_stops_even_if_the_body_raises(self, spy_jobs):
        """ブロック内で例外が起きても、スケジューラを停止してから例外を伝える。"""
        with pytest.raises(RuntimeError, match="body failed"), runner.scheduler_lifespan({runner.SCHEDULER_ENABLED_ENV: "true"}):
            raise RuntimeError("body failed")
        check.equal(spy_jobs.created[0].state, STATE_STOPPED)

    def test_shutdown_does_not_wait_for_running_jobs(self, monkeypatch):
        """停止時は実行中のジョブの終了を待たない(shutdown(wait=False))。"""
        calls = []

        class Recorder(BackgroundScheduler):
            def shutdown(self, wait=True):
                calls.append(wait)
                super().shutdown(wait=wait)

        monkeypatch.setattr(runner, "create_scheduler", lambda: Recorder())
        with runner.scheduler_lifespan({runner.SCHEDULER_ENABLED_ENV: "true"}):
            pass
        check.equal(calls, [False])

    def test_uses_process_environment_by_default(self, spy_jobs, monkeypatch):
        """引数を省略すると os.environ で判定する。"""
        monkeypatch.setenv(runner.SCHEDULER_ENABLED_ENV, "true")
        with runner.scheduler_lifespan() as scheduler:
            check.is_not_none(scheduler)
        monkeypatch.setenv(runner.SCHEDULER_ENABLED_ENV, "false")
        with runner.scheduler_lifespan() as scheduler:
            check.is_none(scheduler)


class TestAppLifespan:
    """FastAPI アプリの lifespan から、スケジューラが起動・停止する。"""

    def test_app_starts_and_stops_scheduler_when_enabled(self, spy_jobs, monkeypatch, clean_env):
        """SCHEDULER_ENABLED=true なら、アプリの起動でスケジューラが動き、終了で停止する(ジョブ本体は実行されない)。"""
        monkeypatch.setenv(runner.SCHEDULER_ENABLED_ENV, "true")
        with TestClient(app) as client:
            check.equal(len(spy_jobs.created), 1)
            check.equal(spy_jobs.created[0].state, STATE_RUNNING)
            check.equal(client.get("/api/v1/public/health/live").status_code, 200)
        check.equal(spy_jobs.created[0].state, STATE_STOPPED)
        check.equal(spy_jobs.calls, [])

    def test_app_does_not_start_scheduler_in_development(self, spy_jobs, monkeypatch):
        """開発環境の既定(未設定 + APP_ENV=development)では、アプリを起動してもスケジューラを作らない。"""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv(runner.SCHEDULER_ENABLED_ENV, raising=False)
        with TestClient(app):
            pass
        check.equal(spy_jobs.created, [])

    def test_app_does_not_start_scheduler_when_disabled_in_production(self, spy_jobs, monkeypatch, clean_env):
        """本番でも SCHEDULER_ENABLED=false なら起動しない(別プロセスに分離した構成)。"""
        monkeypatch.setenv(runner.SCHEDULER_ENABLED_ENV, "false")
        with TestClient(app):
            pass
        check.equal(spy_jobs.created, [])

    def test_app_fails_to_start_with_invalid_value(self, spy_jobs, monkeypatch, clean_env):
        """SCHEDULER_ENABLED が不正なら、アプリの起動時に ValueError(設定の誤りに気づける)。"""
        monkeypatch.setenv(runner.SCHEDULER_ENABLED_ENV, "maybe")
        with pytest.raises(ValueError), TestClient(app):
            pass
