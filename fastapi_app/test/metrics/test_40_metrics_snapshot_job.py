# -*- coding: utf-8 -*-
"""control_plane_app.jobs.metrics_snapshot(日次メトリクスのスナップショット。01 CP-MET-01/02/05)のテスト。

ジョブは台帳の ACTIVE / SUSPENDED の **全テナント**(alpha / beta を含む)を対象にするため、``sandbox``(外側のトランザクション + SAVEPOINT)で
実行して最後にロールバックし、開発 DB の日次メトリクス・ジョブ実行履歴を書き換えない。台帳と AP のデータは使い捨てのテナントで、終了時に削除する。
自分のテナント以外(alpha / beta 等)の集計は、DB を引かずに 0 を返すラッパーに任せ、他のテナントの状態でテストが揺れないようにする。
"""
import datetime as dt
import uuid
from decimal import Decimal

import pytest
import pytest_check as check

from control_plane_app.jobs import metrics_snapshot
from control_plane_app.jobs.metrics_snapshot import JOB_NAME, METRICS_TARGET_STATUSES, run_metrics_snapshot
from control_plane_app.jobs.runner import LOCK_NOT_ACQUIRED
from control_plane_app.models.sql_models import RunStatus, TenantStatus

from .conftest import FakeLock

ALL_STATUSES = [status.value for status in TenantStatus]
SNAPSHOT_AT = dt.datetime(2026, 5, 1, 23, 45, tzinfo=dt.UTC)
SNAPSHOT_DATE = dt.date(2026, 5, 1)
KEYS = {"users_total", "users_active", "todo_count", "todo_open_count", "todo_in_progress_count", "todo_done_count"}


class ScopedMetrics:
    """自分のテナントだけ実際に集計し(``real``)、それ以外は DB を引かずに 0 を返す。``fail`` に入れたテナントは例外にする。"""

    def __init__(self, real, mine, fail=None, message="boom") -> None:
        self.real = real
        self.mine = set(mine)
        self.fail = set(fail or ())
        self.message = message
        self.calls: list[uuid.UUID] = []

    @property
    def metric_keys(self):
        return self.real.metric_keys

    def collect_tenant_metrics(self, tenant_id):
        self.calls.append(tenant_id)
        if tenant_id in self.fail:
            raise RuntimeError(self.message)
        if tenant_id in self.mine:
            return self.real.collect_tenant_metrics(tenant_id)
        return {key: Decimal(0) for key in self.real.metric_keys}


@pytest.fixture
def run_job(sandbox, collector):
    """``run_job(mine, fail=..., at=..., lock=...)``: サンドボックス上でジョブを実行する。"""

    def run(mine, *, fail=(), at=SNAPSHOT_AT, lock=None, message="boom"):
        metrics = ScopedMetrics(collector, [t.id for t in mine], [t.id for t in fail], message)
        result = run_metrics_snapshot(session_factory=sandbox.session, metrics=metrics, lock=lock or FakeLock(), clock=lambda: at)
        return result, metrics

    return run


class TestTargetStatuses:
    """対象のテナントは ACTIVE と SUSPENDED のみ(停止中も推移を途切れさせない)。"""

    def test_target_status_constant(self):
        """対象の状態の定義は ACTIVE と SUSPENDED だけ。"""
        check.equal(set(METRICS_TARGET_STATUSES), {TenantStatus.ACTIVE, TenantStatus.SUSPENDED})

    def test_only_active_and_suspended_are_collected(self, run_job, sandbox, metric_tenant):
        """すべての状態のテナントを作って実行すると、ACTIVE と SUSPENDED だけを集計・保存する。他の状態のテナントは集計も保存もしない。"""
        tenants = {status: metric_tenant(status) for status in ALL_STATUSES}
        result, metrics = run_job(list(tenants.values()))
        collected = {t.status for t in tenants.values() if t.id in metrics.calls}
        check.equal(collected, {"ACTIVE", "SUSPENDED"})
        saved = {status: sandbox.metrics(tenant.id) for status, tenant in tenants.items()}
        for status, rows in saved.items():
            if status in ("ACTIVE", "SUSPENDED"):
                check.equal({key for _, key in rows}, KEYS, status)
            else:
                check.equal(rows, {}, status)
        listed = set(result.detail["tenants"])
        check.is_true({str(tenants["ACTIVE"].id), str(tenants["SUSPENDED"].id)} <= listed)
        check.equal(listed & {str(t.id) for status, t in tenants.items() if status not in ("ACTIVE", "SUSPENDED")}, set())

    def test_suspended_tenant_data_is_still_collected(self, run_job, sandbox, ap_db, metric_tenant):
        """停止中のテナントも、残っているデータの実値を保存する。"""
        tenant = metric_tenant("SUSPENDED")
        ap_db.add_user(tenant.ctx)
        run_job([tenant])
        check.equal(sandbox.metrics(tenant.id)[(SNAPSHOT_DATE, "users_total")], Decimal(1))


class TestSnapshotValues:
    """保存する値。"""

    def test_saves_user_and_todo_values_per_tenant(self, run_job, sandbox, ap_db, metric_tenant):
        """ユーザー数(総数・有効数)と ToDo の件数(論理削除を除く、状態別)を、テナントごとに自分の分だけ保存する。"""
        a, b = metric_tenant(), metric_tenant()
        users = [ap_db.add_user(a.ctx), ap_db.add_user(a.ctx), ap_db.add_user(a.ctx, is_active=False)]
        for status in ("open", "open", "done"):
            ap_db.add_todo(a.ctx, users[0].id, status=status)
        ap_db.add_todo(a.ctx, users[0].id, status="done", deleted=True)
        other = ap_db.add_user(b.ctx)
        ap_db.add_todo(b.ctx, other.id, status="in_progress")
        result, _ = run_job([a, b])
        check.equal(result.status, RunStatus.SUCCEEDED)
        check.equal(
            {key: value for (_, key), value in sandbox.metrics(a.id).items()},
            {"users_total": 3, "users_active": 2, "todo_count": 3, "todo_open_count": 2, "todo_in_progress_count": 0, "todo_done_count": 1},
        )
        check.equal(
            {key: value for (_, key), value in sandbox.metrics(b.id).items()},
            {"users_total": 1, "users_active": 1, "todo_count": 1, "todo_open_count": 0, "todo_in_progress_count": 1, "todo_done_count": 0},
        )

    def test_rows_are_dated_with_the_utc_day_of_the_clock(self, run_job, sandbox, metric_tenant):
        """集計対象日は実行時点の UTC の当日。UTC 以外のタイムゾーンの時計でも UTC に直した日付になる。"""
        tenant = metric_tenant()
        jst = dt.timezone(dt.timedelta(hours=9))
        run_job([tenant], at=dt.datetime(2026, 5, 2, 3, 0, tzinfo=jst))  # UTC では 5/1 18:00
        check.equal({date for date, _ in sandbox.metrics(tenant.id)}, {dt.date(2026, 5, 1)})
        run_job([tenant], at=dt.datetime(2026, 5, 3, 0, 0, tzinfo=dt.UTC))
        check.equal({date for date, _ in sandbox.metrics(tenant.id)}, {dt.date(2026, 5, 1), dt.date(2026, 5, 3)})

    def test_result_detail(self, run_job, metric_tenant):
        """結果の detail に、日付・指標キー・成功したテナント・変更行数・失敗(空)が入る。"""
        tenant = metric_tenant()
        result, _ = run_job([tenant])
        detail = result.detail
        check.equal((detail["date"], detail["failed"]), ("2026-05-01", {}))
        check.equal(set(detail["metric_keys"]), KEYS)
        check.is_in(str(tenant.id), detail["tenants"])
        check.greater_equal(detail["rows_changed"], len(KEYS))
        check.is_none(result.error)

    def test_run_is_recorded(self, run_job, sandbox, metric_tenant):
        """実行履歴(t_scheduled_job_run)に job_name と SUCCEEDED、開始・終了日時を残す。"""
        result, _ = run_job([metric_tenant()])
        record = sandbox.rows("SELECT * FROM t_scheduled_job_run WHERE id = :id", id=result.run_id)[0]
        check.equal((record["job_name"], record["status"], record["error"]), (JOB_NAME, "SUCCEEDED", None))
        check.is_not_none(record["finished_at"])
        check.equal(record["started_at"], SNAPSHOT_AT)


class TestIdempotency:
    """同じ日の再実行は上書きで、行は増えない。"""

    def test_rerun_same_day_changes_nothing(self, run_job, sandbox, ap_db, metric_tenant):
        """データが変わらないまま同じ日に再実行しても、保存済みの行は増えず、変更行数は 0(自分のテナント分)。"""
        tenant = metric_tenant()
        ap_db.add_user(tenant.ctx)
        run_job([tenant])
        first = sandbox.metrics(tenant.id)
        result, _ = run_job([tenant])
        check.equal(sandbox.metrics(tenant.id), first)
        check.equal(len(first), len(KEYS))
        check.equal(result.detail["rows_changed"], 0)

    def test_rerun_overwrites_changed_values(self, run_job, sandbox, ap_db, metric_tenant):
        """同じ日に再実行してデータが増えていれば、その日の行の値を上書きする(行数は変わらない)。"""
        tenant = metric_tenant()
        ap_db.add_user(tenant.ctx)
        run_job([tenant])
        ap_db.add_user(tenant.ctx)
        ap_db.add_user(tenant.ctx, is_active=False)
        result, _ = run_job([tenant])
        saved = sandbox.metrics(tenant.id)
        check.equal(len(saved), len(KEYS))
        check.equal((saved[(SNAPSHOT_DATE, "users_total")], saved[(SNAPSHOT_DATE, "users_active")]), (Decimal(3), Decimal(2)))
        check.equal(result.detail["rows_changed"], 2)

    def test_next_day_adds_rows(self, run_job, sandbox, metric_tenant):
        """翌日の実行は新しい日付の行を追加する(前日の行は残る)。"""
        tenant = metric_tenant()
        run_job([tenant])
        run_job([tenant], at=SNAPSHOT_AT + dt.timedelta(days=1))
        check.equal(len(sandbox.metrics(tenant.id)), 2 * len(KEYS))


class TestFailureIsolation:
    """1 テナントの失敗で他のテナントの処理を止めない。"""

    def test_one_failing_tenant_marks_job_failed_and_others_continue(self, run_job, sandbox, ap_db, metric_tenant):
        """あるテナントの集計が失敗しても、他のテナントは処理して保存する。ジョブは FAILED で、失敗したテナントと例外の型だけを error・detail に残し、そのテナントの行は保存しない。"""
        bad, good1, good2 = metric_tenant(), metric_tenant(), metric_tenant()
        ap_db.add_user(good1.ctx)
        ap_db.add_user(good2.ctx)
        result, _ = run_job([bad, good1, good2], fail=[bad], message="secret-detail-xyz")
        check.equal(result.status, RunStatus.FAILED)
        check.equal(result.detail["failed"], {str(bad.id): "RuntimeError"})
        check.is_in(f"{bad.id}=RuntimeError", result.error)
        check.is_in("1 tenant(s) failed", result.error)
        check.is_not_in("secret-detail-xyz", result.error + repr(result.detail))
        check.equal(sandbox.metrics(bad.id), {})
        check.is_not_in(str(bad.id), result.detail["tenants"])
        for good in (good1, good2):
            check.is_in(str(good.id), result.detail["tenants"])
            check.equal(len(sandbox.metrics(good.id)), len(KEYS))
        check.equal(sandbox.metrics(good1.id)[(SNAPSHOT_DATE, "users_total")], Decimal(1))

    def test_failed_run_is_recorded_as_failed(self, run_job, sandbox, metric_tenant):
        """失敗した実行は履歴に FAILED と error(秘匿値を含まない要約)を残す。"""
        bad = metric_tenant()
        result, _ = run_job([bad], fail=[bad], message="secret-detail-xyz")
        record = sandbox.rows("SELECT * FROM t_scheduled_job_run WHERE id = :id", id=result.run_id)[0]
        check.equal(record["status"], "FAILED")
        check.is_in(str(bad.id), record["error"])
        check.is_not_in("secret-detail-xyz", record["error"])

    def test_next_run_recovers(self, run_job, sandbox, metric_tenant):
        """障害が直った次の実行で、失敗していたテナントの行が保存され、ジョブは SUCCEEDED に戻る。"""
        bad = metric_tenant()
        run_job([bad], fail=[bad])
        result, _ = run_job([bad])
        check.equal(result.status, RunStatus.SUCCEEDED)
        check.equal(len(sandbox.metrics(bad.id)), len(KEYS))


    def test_setup_error_fails_the_whole_job_without_saving(self, sandbox, metric_tenant, monkeypatch):
        """指標セットの不整合(キー重複など。集計リポジトリの生成時の ValueError)はジョブ全体が FAILED(error は例外の型だけ)で、どのテナントの行も保存しない。"""
        tenant = metric_tenant()

        def broken(*args, **kwargs):
            raise ValueError("metric key 'users_total' is defined by both 'users' and 'clash'")

        monkeypatch.setattr(metrics_snapshot, "AppTenantMetricsRepository", broken)
        result = run_metrics_snapshot(session_factory=sandbox.session, lock=FakeLock(), clock=lambda: SNAPSHOT_AT)
        check.equal((result.status, result.error), (RunStatus.FAILED, "error=ValueError"))
        check.equal(sandbox.metrics(tenant.id), {})
        record = sandbox.rows("SELECT * FROM t_scheduled_job_run WHERE id = :id", id=result.run_id)[0]
        check.equal((record["status"], record["error"]), ("FAILED", "error=ValueError"))


class TestLock:
    """二重実行の防止(ジョブ名の advisory lock)。"""

    def test_lock_not_acquired_skips_without_collecting(self, run_job, sandbox, metric_tenant):
        """ロックを取得できなければ SKIPPED(error=lock_not_acquired)を記録して何も集計しない。"""
        tenant = metric_tenant()
        lock = FakeLock(acquired=False)
        result, metrics = run_job([tenant], lock=lock)
        check.equal((result.status, result.error), (RunStatus.SKIPPED, LOCK_NOT_ACQUIRED))
        check.equal(metrics.calls, [])
        check.equal(sandbox.metrics(tenant.id), {})
        check.equal(lock.keys, [JOB_NAME])
