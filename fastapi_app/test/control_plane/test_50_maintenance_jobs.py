# -*- coding: utf-8 -*-
"""control_plane_app の保守処理(回収 reaper・削除対象の抽出)と定期ジョブ(二重実行防止・実行履歴)のテスト。

ジョブは対象テーブル全体を走査するため、開発 DB に他のテナントが PROVISIONING / PENDING_DELETION / DEPROVISIONING で
存在する場合は、巻き込まないようテストを skip する(``JobEnvironmentGuard``)。
"""
import datetime as dt

import pytest
import pytest_check as check

from control_plane_app.jobs.provisioning_reaper import JOB_NAME as REAPER_JOB_NAME
from control_plane_app.jobs.provisioning_reaper import run_provisioning_reaper
from control_plane_app.jobs.runner import LOCK_NOT_ACQUIRED, JobOutcome, run_scheduled_job
from control_plane_app.jobs.tenant_purge import JOB_NAME as PURGE_JOB_NAME
from control_plane_app.jobs.tenant_purge import run_tenant_purge
from control_plane_app.models.sql_models import RunStatus
from control_plane_app.repositories.locks import PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.tenant_maintenance import REAPED_ERROR, list_deprovisionable_tenant_ids, reap_stale_provisioning
from modules.keycloak_admin.errors import KeycloakAdminError

from .conftest import FakeAdmin, JobEnvironmentGuard, initial_admin

MINUTE = dt.timedelta(minutes=1)
DAY = dt.timedelta(days=1)


@pytest.fixture
def guard(cp_db) -> None:
    """ジョブが他のテナントを巻き込まない環境であることを確認する(そうでなければ skip)。"""
    JobEnvironmentGuard.require_clean(cp_db, ("PROVISIONING", "PENDING_DELETION", "DEPROVISIONING"))


def stale_provisioning_tenant(cp_db):
    return cp_db.insert_tenant(status="PROVISIONING", version=1, with_running_history=True)


@pytest.mark.usefixtures("guard")
class TestReapStaleProvisioning:
    """reap_stale_provisioning: 長時間 PROVISIONING のままの払い出しを FAILED にする(CP-ONB-09)。"""

    def test_stale_tenant_becomes_failed(self, cp_db, clock):
        """10 分以上 PROVISIONING のままのテナントは FAILED(バージョン +1)になり、RUNNING の履歴は FAILED で閉じ、tenant.provision_reap を残す。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=11)
        with cp_db.session() as session:
            reaped = reap_stale_provisioning(session, clock=clock)
        check.equal(reaped, [tenant_id])
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"], row["updated_by"]), ("FAILED", 2, "system"))
        history = cp_db.histories(tenant_id)[0]
        check.equal((history["status"], history["error"]), ("FAILED", f"step=ensure_tenant_realm; error={REAPED_ERROR}"))
        check.is_not_none(history["finished_at"])
        audit = cp_db.audits(tenant_id)
        check.equal([a["action"] for a in audit], ["tenant.provision_reap"])
        check.equal((audit[0]["actor"], audit[0]["payload"]["closed_histories"]), ("system", 1))
        check.equal(audit[0]["payload"]["status"], {"before": "PROVISIONING", "after": "FAILED"})

    def test_fresh_tenant_is_left_alone(self, cp_db, clock):
        """しきい値(10 分)に満たない(9 分)PROVISIONING は回収しない。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=9)
        with cp_db.session() as session:
            check.equal(reap_stale_provisioning(session, clock=clock), [])
        check.equal(cp_db.tenant(tenant_id)["status"], "PROVISIONING")
        check.equal(cp_db.audits(tenant_id), [])

    def test_threshold_is_configurable(self, cp_db, clock):
        """しきい値は引数で変えられる(1 分にすれば 2 分経過で回収、1 時間にすれば 11 分では回収しない)。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=11)
        with cp_db.session() as session:
            check.equal(reap_stale_provisioning(session, threshold=dt.timedelta(hours=1), clock=clock), [])
            check.equal(reap_stale_provisioning(session, threshold=MINUTE, clock=clock), [tenant_id])

    @pytest.mark.parametrize("status", ["ACTIVE", "FAILED", "SUSPENDED", "PENDING_DELETION", "DELETED"])
    def test_only_provisioning_is_reaped(self, cp_db, clock, status):
        """PROVISIONING 以外の状態は、どれだけ古くても回収しない。"""
        tenant_id = cp_db.insert_tenant(status=status, version=3)
        clock.advance(days=3)
        with cp_db.session() as session:
            check.equal(reap_stale_provisioning(session, clock=clock), [])
        row = cp_db.tenant(tenant_id)
        check.equal((row["status"], row["version"]), (status, 3))

    def test_tenant_with_operation_in_progress_is_skipped(self, cp_db, clock):
        """払い出しが実行中(テナントのロック保持中)のテナントは対象外。ロックが外れた後の実行で回収される。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        clock.advance(minutes=11)
        with PgAdvisoryLock(cp_db.runtime).try_acquire(tenant_lock_key(code)) as acquired:
            check.is_true(acquired)
            with cp_db.session() as session:
                check.equal(reap_stale_provisioning(session, clock=clock), [])
            check.equal(cp_db.tenant(tenant_id)["status"], "PROVISIONING")
        with cp_db.session() as session:
            check.equal(reap_stale_provisioning(session, clock=clock), [tenant_id])

    def test_idempotent(self, cp_db, clock):
        """続けて 2 回実行しても、2 回目は何もしない(バージョンも監査ログも増えない)。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=11)
        with cp_db.session() as session:
            check.equal(reap_stale_provisioning(session, clock=clock), [tenant_id])
            check.equal(reap_stale_provisioning(session, clock=clock), [])
        check.equal((cp_db.tenant(tenant_id)["version"], len(cp_db.audits(tenant_id))), (2, 1))

    def test_reaped_tenant_can_be_retried(self, cp_db, clock, make_service, fake_kc):
        """回収して FAILED になったテナントは retry で払い出しをやり直せる。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=11)
        with cp_db.session() as session:
            reap_stale_provisioning(session, clock=clock)
        result = make_service().retry(tenant_id, initial_admin=initial_admin(), actor="cp-admin")
        check.equal(result.tenant.status, "ACTIVE")
        check.equal(cp_db.audit_actions(tenant_id), ["tenant.provision_reap", "tenant.provision_retry", "tenant.provision_succeed"])

    def test_custom_actor(self, cp_db, clock):
        """操作者は引数で変えられる。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=11)
        with cp_db.session() as session:
            reap_stale_provisioning(session, actor="reaper-x", clock=clock)
        check.equal((cp_db.tenant(tenant_id)["updated_by"], cp_db.audits(tenant_id)[0]["actor"]), ("reaper-x", "reaper-x"))


@pytest.mark.usefixtures("guard")
class TestListDeprovisionable:
    """list_deprovisionable_tenant_ids: 物理削除の対象の抽出。"""

    def test_selection(self, cp_db, clock):
        """猶予期間を過ぎた PENDING_DELETION と DEPROVISIONING だけが対象。猶予中・他の状態は対象外。要求日時の古い順。"""
        old = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - 40 * DAY)
        newer = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - 31 * DAY)
        within = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - 29 * DAY)
        failed_before = cp_db.insert_tenant(status="DEPROVISIONING", deletion_requested_at=clock.now - 5 * DAY)
        for status in ("ACTIVE", "SUSPENDED", "FAILED", "DELETED", "PROVISIONING"):
            cp_db.insert_tenant(status=status, deletion_requested_at=clock.now - 90 * DAY)
        with cp_db.session() as session:
            selected = list_deprovisionable_tenant_ids(session, clock=clock)
        check.equal(set(selected), {old, newer, failed_before})
        check.is_not_in(within, selected)
        check.is_true(selected.index(old) < selected.index(newer), "削除要求日時の古い順")

    def test_boundary_is_inclusive(self, cp_db, clock):
        """削除要求からちょうど 30 日の PENDING_DELETION は対象(deprovision が許可する境界と一致)。"""
        exact = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - 30 * DAY)
        just_short = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - 30 * DAY + dt.timedelta(seconds=1))
        with cp_db.session() as session:
            selected = list_deprovisionable_tenant_ids(session, clock=clock)
        check.is_in(exact, selected)
        check.is_not_in(just_short, selected)

    def test_grace_period_override(self, cp_db, clock):
        """猶予期間は引数で変えられる。"""
        tenant_id = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - 8 * DAY)
        with cp_db.session() as session:
            check.is_not_in(tenant_id, list_deprovisionable_tenant_ids(session, clock=clock))
            check.is_in(tenant_id, list_deprovisionable_tenant_ids(session, grace_period=7 * DAY, clock=clock))

    def test_agrees_with_service_decision(self, cp_db, clock, make_service, fake_kc):
        """抽出された対象は、すべて deprovision が実行を許可する(抽出と実行の境界が食い違わない)。"""
        for ago in (31 * DAY, 30 * DAY):
            tenant_id = cp_db.insert_tenant(status="PENDING_DELETION", deletion_requested_at=clock.now - ago)
            fake_kc.realms[cp_db.tenant(tenant_id)["realm_name"]] = False
        with cp_db.session() as session:
            selected = list_deprovisionable_tenant_ids(session, clock=clock)
        check.equal(len(selected), 2)
        for tenant_id in selected:
            check.equal(make_service().deprovision(tenant_id).tenant.status, "DELETED")


@pytest.mark.usefixtures("guard")
class TestReaperJob:
    """run_provisioning_reaper(ジョブ本体)。"""

    def test_job_records_run_and_reaps(self, cp_db, clock):
        """ジョブは回収を実行し、実行履歴(SUCCEEDED・終了日時あり)と回収したテナント ID を返す。"""
        tenant_id = stale_provisioning_tenant(cp_db)
        clock.advance(minutes=11)
        result = run_provisioning_reaper(session_factory=cp_db.session, clock=clock)
        cp_db.job_run_ids.append(result.run_id)
        check.equal((result.job_name, result.status, result.error), (REAPER_JOB_NAME, RunStatus.SUCCEEDED, None))
        check.equal(result.detail["reaped"], [str(tenant_id)])
        run = cp_db.job_run(result.run_id)
        check.equal((run["job_name"], run["status"], run["error"]), (REAPER_JOB_NAME, "SUCCEEDED", None))
        check.is_not_none(run["finished_at"])
        check.equal(cp_db.tenant(tenant_id)["status"], "FAILED")

    def test_job_with_nothing_to_do(self, cp_db, clock):
        """対象が無くても SUCCEEDED で、reaped は空。"""
        result = run_provisioning_reaper(session_factory=cp_db.session, clock=clock)
        cp_db.job_run_ids.append(result.run_id)
        check.equal((result.status, result.detail["reaped"]), (RunStatus.SUCCEEDED, []))


@pytest.mark.usefixtures("guard")
class TestPurgeJob:
    """run_tenant_purge(ジョブ本体)。"""

    def run(self, cp_db, fake_app_data, clock, admin_factory=None, **kwargs):
        admins = []

        def factory():
            admin = FakeAdmin()
            admins.append(admin)
            return admin

        result = run_tenant_purge(session_factory=cp_db.session, admin_factory=admin_factory or factory, app_data=fake_app_data, clock=clock, **kwargs)
        cp_db.job_run_ids.append(result.run_id)
        return result, admins

    def pending(self, cp_db, fake_kc, clock, ago, status="PENDING_DELETION"):
        tenant_id = cp_db.insert_tenant(status=status, version=3, deletion_requested_at=clock.now - ago)
        fake_kc.realms[cp_db.tenant(tenant_id)["realm_name"]] = False
        return tenant_id

    def test_deletes_only_due_tenants(self, cp_db, fake_kc, fake_app_data, clock):
        """猶予期間を過ぎた PENDING_DELETION と DEPROVISIONING だけを削除し、猶予中のテナントは残す。テナントごとに管理クライアントを作って閉じる。"""
        due = self.pending(cp_db, fake_kc, clock, 31 * DAY)
        resumed = self.pending(cp_db, fake_kc, clock, 2 * DAY, status="DEPROVISIONING")
        within = self.pending(cp_db, fake_kc, clock, 5 * DAY)
        result, admins = self.run(cp_db, fake_app_data, clock)
        check.equal((result.job_name, result.status, result.error), (PURGE_JOB_NAME, RunStatus.SUCCEEDED, None))
        check.equal(set(result.detail["deleted"]), {str(due), str(resumed)})
        check.equal(result.detail["failed"], {})
        check.equal((cp_db.tenant(due)["status"], cp_db.tenant(resumed)["status"], cp_db.tenant(within)["status"]), ("DELETED", "DELETED", "PENDING_DELETION"))
        check.equal(len(admins), 2, "管理クライアントはテナントごとに作る(締め切りは 1 テナントの処理に対して適用)")
        check.is_true(all(admin.closed for admin in admins))
        check.equal(set(fake_app_data.calls), {due, resumed})

    def test_one_failure_does_not_stop_others_and_fails_the_job(self, cp_db, fake_kc, fake_app_data, clock):
        """1 テナントの削除が失敗しても他のテナントの処理は続け、ジョブは FAILED(失敗したテナントは DEPROVISIONING のまま次回再試行)。"""
        good = self.pending(cp_db, fake_kc, clock, 40 * DAY)
        bad = self.pending(cp_db, fake_kc, clock, 35 * DAY)
        bad_realm = cp_db.tenant(bad)["realm_name"]

        def hook(kwargs):
            if kwargs["realm_name"] == bad_realm:
                raise KeycloakAdminError("delete realm", 500, "errorMessage=KC-SECRET-DETAIL")

        fake_kc.hooks["delete_realm_if_exists"] = hook
        result, _ = self.run(cp_db, fake_app_data, clock)
        check.equal(result.status, RunStatus.FAILED)
        check.equal(result.detail["deleted"], [str(good)])
        check.equal(result.detail["failed"], {str(bad): "tenant_deprovisioning_failed"})
        check.equal(cp_db.tenant(good)["status"], "DELETED")
        check.equal(cp_db.tenant(bad)["status"], "DEPROVISIONING")
        run = cp_db.job_run(result.run_id)
        check.equal(run["status"], "FAILED")
        check.is_in(str(bad), run["error"])
        check.is_in("tenant_deprovisioning_failed", run["error"])
        check.is_not_in("KC-SECRET-DETAIL", repr(run))
        # 次回の実行で再試行され、収束する
        fake_kc.hooks.clear()
        again, _ = self.run(cp_db, fake_app_data, clock)
        check.equal((again.status, again.detail["deleted"]), (RunStatus.SUCCEEDED, [str(bad)]))
        check.equal(cp_db.tenant(bad)["status"], "DELETED")

    def test_unexpected_error_is_recorded_by_type_and_others_continue(self, cp_db, fake_kc, fake_app_data, clock):
        """管理クライアントの生成など予期しない例外は型名だけを記録し、他のテナントは処理する。"""
        first = self.pending(cp_db, fake_kc, clock, 50 * DAY)
        second = self.pending(cp_db, fake_kc, clock, 45 * DAY)
        calls = []

        def factory():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("provisioner secret=LEAK")
            return FakeAdmin()

        result, _ = self.run(cp_db, fake_app_data, clock, admin_factory=factory)
        check.equal(result.status, RunStatus.FAILED)
        check.equal(result.detail["failed"], {str(first): "RuntimeError"})
        check.equal(result.detail["deleted"], [str(second)])
        check.is_not_in("LEAK", repr(cp_db.job_run(result.run_id)))
        check.equal(cp_db.tenant(first)["status"], "PENDING_DELETION")

    def test_nothing_to_do(self, cp_db, fake_app_data, clock):
        """対象が無ければ SUCCEEDED で何もしない。"""
        result, admins = self.run(cp_db, fake_app_data, clock)
        check.equal((result.status, result.detail, admins), (RunStatus.SUCCEEDED, {"deleted": [], "failed": {}}, []))


class TestRunScheduledJob:
    """run_scheduled_job: 二重実行防止と実行履歴(専用のジョブ名を使うため、他のテナントを巻き込まない)。"""

    @pytest.fixture
    def job_name(self, cp_db) -> str:
        import uuid

        return f"zt_job_{uuid.uuid4().hex[:8]}"

    def run(self, cp_db, job_name, body, **kwargs):
        result = run_scheduled_job(job_name, body, session_factory=cp_db.session, **kwargs)
        cp_db.job_run_ids.append(result.run_id)
        return result

    def test_success(self, cp_db, job_name):
        """本体が成功すれば SUCCEEDED。実行履歴に開始・終了日時が残り、本体の detail が返る。"""
        result = self.run(cp_db, job_name, lambda session: JobOutcome(detail={"n": 1}))
        run = cp_db.job_run(result.run_id)
        check.equal((result.status, result.detail, result.error), (RunStatus.SUCCEEDED, {"n": 1}, None))
        check.equal((run["status"], run["job_name"], run["error"]), ("SUCCEEDED", job_name, None))
        check.is_true(run["started_at"] is not None and run["finished_at"] is not None)

    def test_running_is_committed_before_body(self, cp_db, job_name):
        """本体の実行中は、別の接続から RUNNING の実行履歴が見える(開始を先にコミットする)。"""
        seen = {}

        def body(session):
            from sqlalchemy import text

            with cp_db.runtime.connect() as connection:
                seen["row"] = connection.execute(text("SELECT status, finished_at FROM t_scheduled_job_run WHERE job_name = :n"), {"n": job_name}).first()
            return JobOutcome()

        self.run(cp_db, job_name, body)
        check.equal(tuple(seen["row"]), ("RUNNING", None))

    def test_exception_is_recorded_without_message(self, cp_db, job_name):
        """本体が例外を送出しても伝播させず FAILED として記録する。記録するのは型名だけ(メッセージの秘匿値を残さない)。"""

        def body(session):
            raise ValueError("password=TOPSECRET")

        result = self.run(cp_db, job_name, body)
        run = cp_db.job_run(result.run_id)
        check.equal((result.status, result.error), (RunStatus.FAILED, "error=ValueError"))
        check.equal((run["status"], run["error"]), ("FAILED", "error=ValueError"))
        check.is_not_none(run["finished_at"])

    def test_outcome_error_marks_failed(self, cp_db, job_name):
        """本体が error を返した(一部失敗)場合は FAILED。"""
        result = self.run(cp_db, job_name, lambda session: JobOutcome(detail={"x": 1}, error="1 tenant(s) failed"))
        check.equal((result.status, cp_db.job_run(result.run_id)["error"]), (RunStatus.FAILED, "1 tenant(s) failed"))

    def test_skipped_when_another_run_holds_the_lock(self, cp_db, job_name):
        """同じジョブが実行中(ロック保持中)なら本体を呼ばずに SKIPPED を記録する(二重実行防止)。"""
        called = []
        with PgAdvisoryLock(cp_db.runtime).try_acquire(job_name) as acquired:
            check.is_true(acquired)
            result = self.run(cp_db, job_name, lambda session: called.append(1) or JobOutcome())
        run = cp_db.job_run(result.run_id)
        check.equal((result.status, result.error, called), (RunStatus.SKIPPED, LOCK_NOT_ACQUIRED, []))
        check.equal((run["status"], run["error"]), ("SKIPPED", LOCK_NOT_ACQUIRED))
        check.is_not_none(run["finished_at"])

    def test_lock_is_released_after_run(self, cp_db, job_name):
        """実行後(失敗時を含む)はジョブのロックが解放され、次の実行が SKIPPED にならない。"""
        self.run(cp_db, job_name, lambda session: (_ for _ in ()).throw(RuntimeError("x")))
        second = self.run(cp_db, job_name, lambda session: JobOutcome())
        check.equal(second.status, RunStatus.SUCCEEDED)

