# -*- coding: utf-8 -*-
"""AppTenantMetricsRepository(CP から AP DB のテナント毎のメトリクスを集計する)と、ユーザー数・ToDo の指標のテスト。

開発 DB の ``app_db`` に、使い捨てのテナントのユーザー・ToDo を作る。集計は ``app_cp_agent``(SELECT / DELETE のみ、RLS 適用)で、
テナントごとに GUC を切り替えて行うため、他のテナントの行を数えないことを確認する。終了時にすべて削除する。
"""
import uuid
from decimal import Decimal

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlmodel import Session

from control_plane_app.repositories.app_tenant_metrics import USER_METRICS, AppTenantMetricsRepository
from main_app.repositories.todos.metrics import TODO_METRICS
from modules.tenancy.db import tenant_guc_scope
from modules.tenant_metrics.definition import TenantMetricSet

USER_KEYS = {"users_total": 0, "users_active": 0}
TODO_KEYS = {"todo_count": 0, "todo_open_count": 0, "todo_in_progress_count": 0, "todo_done_count": 0}


def expected(**values):
    return {key: Decimal(values.get(key, 0)) for key in (*USER_KEYS, *TODO_KEYS)}


def seed_users(ap_db, ctx, active: int, inactive: int = 0):
    users = [ap_db.add_user(ctx, is_active=True) for _ in range(active)] + [ap_db.add_user(ctx, is_active=False) for _ in range(inactive)]
    return users


class TestUserMetrics:
    """ユーザー数(基盤の指標。CP-MET-01)。"""

    def test_counts_total_and_active(self, ap_db, collector, metric_tenant):
        """総数と有効数を数える(無効化されたユーザーは総数にだけ含まれる)。値は Decimal。"""
        tenant = metric_tenant()
        seed_users(ap_db, tenant.ctx, active=3, inactive=2)
        values = collector.collect_tenant_metrics(tenant.id)
        check.equal(values, expected(users_total=5, users_active=3))
        check.is_true(all(isinstance(v, Decimal) for v in values.values()))

    def test_zero_when_no_rows(self, collector, metric_tenant):
        """行が 1 件も無いテナントは、すべての指標が 0(キーは欠けない)。"""
        check.equal(collector.collect_tenant_metrics(metric_tenant().id), expected())

    def test_unknown_tenant_is_zero(self, collector):
        """存在しないテナント ID は 0(エラーにしない)。"""
        check.equal(collector.collect_tenant_metrics(uuid.uuid4()), expected())


class TestRlsIsolation:
    """RLS 越しの集計は、他テナントの行を数えない(tenant-isolation §5.1)。"""

    def test_each_tenant_counts_only_its_own_rows(self, ap_db, collector, metric_tenant):
        """2 つのテナントのユーザー・ToDo を、それぞれのテナントの集計が自分の分だけ数える。"""
        a, b = metric_tenant(), metric_tenant()
        users_a = seed_users(ap_db, a.ctx, active=2, inactive=1)
        users_b = seed_users(ap_db, b.ctx, active=5)
        for status in ("open", "open", "done"):
            ap_db.add_todo(a.ctx, users_a[0].id, status=status)
        for status in ("in_progress",) * 4:
            ap_db.add_todo(b.ctx, users_b[0].id, status=status)
        check.equal(collector.collect_tenant_metrics(a.id), expected(users_total=3, users_active=2, todo_count=3, todo_open_count=2, todo_done_count=1))
        check.equal(collector.collect_tenant_metrics(b.id), expected(users_total=5, users_active=5, todo_count=4, todo_in_progress_count=4))

    def test_aggregation_does_not_depend_on_call_order(self, ap_db, collector, metric_tenant):
        """A → B → A と続けて集計しても、接続を再利用した GUC の残りで値が混ざらない。"""
        a, b = metric_tenant(), metric_tenant()
        seed_users(ap_db, a.ctx, active=1)
        seed_users(ap_db, b.ctx, active=4)
        results = [collector.collect_tenant_metrics(t.id)["users_total"] for t in (a, b, a, b, a)]
        check.equal(results, [Decimal(1), Decimal(4), Decimal(1), Decimal(4), Decimal(1)])

    def test_collector_with_mismatching_guc_and_tenant_id_counts_nothing(self, ap_db, app_cp_agent_engine, metric_tenant):
        """GUC のテナントと tenant_id 引数が食い違う場合(呼び出しの誤り)は、RLS と tenant_id 条件の両方で 0 件になる。"""
        a, b = metric_tenant(), metric_tenant()
        seed_users(ap_db, a.ctx, active=2)
        seed_users(ap_db, b.ctx, active=3)
        with Session(app_cp_agent_engine) as session:
            try:
                with tenant_guc_scope(session, b.id):
                    mismatch = USER_METRICS.collect_values(session, a.id)
                with tenant_guc_scope(session, a.id):
                    matching = USER_METRICS.collect_values(session, a.id)
            finally:
                session.rollback()
        check.equal(mismatch, {"users_total": Decimal(0), "users_active": Decimal(0)})
        check.equal(matching, {"users_total": Decimal(2), "users_active": Decimal(2)})

    def test_todo_collector_with_mismatching_guc_counts_nothing(self, ap_db, app_cp_agent_engine, metric_tenant):
        """ToDo の指標も、GUC と tenant_id 引数が食い違えば 0 件(他テナントの ToDo を数えない)。"""
        a, b = metric_tenant(), metric_tenant()
        owner = seed_users(ap_db, a.ctx, active=1)[0]
        ap_db.add_todo(a.ctx, owner.id)
        with Session(app_cp_agent_engine) as session:
            try:
                with tenant_guc_scope(session, b.id):
                    mismatch = TODO_METRICS.collect_values(session, a.id)
                with tenant_guc_scope(session, b.id):
                    other = TODO_METRICS.collect_values(session, b.id)
            finally:
                session.rollback()
        check.equal(set(mismatch.values()) | set(other.values()), {Decimal(0)})

    def test_without_guc_agent_sees_nothing(self, ap_db, app_cp_agent_engine, metric_tenant):
        """GUC を設定しない app_cp_agent は、どのテナントの行も見えない(コンテキスト無しは 0 件)。"""
        tenant = metric_tenant()
        owner = seed_users(ap_db, tenant.ctx, active=1)[0]
        ap_db.add_todo(tenant.ctx, owner.id)
        with app_cp_agent_engine.connect() as connection:
            counts = [connection.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :id"), {"id": tenant.id}).scalar_one() for table in ("t_user", "t_todo")]
        check.equal(counts, [0, 0])

    def test_collection_does_not_write(self, ap_db, collector, metric_tenant):
        """集計は読み取りだけ(行・監査ログが増えない。app_cp_agent は INSERT / UPDATE できない)。"""
        tenant = metric_tenant()
        seed_users(ap_db, tenant.ctx, active=2)
        before = (len(ap_db.users(tenant.ctx)), len(ap_db.audits(tenant.ctx)))
        collector.collect_tenant_metrics(tenant.id)
        check.equal((len(ap_db.users(tenant.ctx)), len(ap_db.audits(tenant.ctx))), before)


class TestTodoMetrics:
    """ToDo の指標(docs/spec/ToDoApp.md §7 #5)。論理削除を除き、ステータス別に数える。"""

    def test_status_breakdown_excludes_soft_deleted(self, ap_db, collector, metric_tenant):
        """todo_count は論理削除を除く総数で、open / in_progress / done は状態別。論理削除済みはどの指標にも入らない。"""
        tenant = metric_tenant()
        owner = seed_users(ap_db, tenant.ctx, active=1)[0]
        for status, count in (("open", 2), ("in_progress", 3), ("done", 4)):
            for _ in range(count):
                ap_db.add_todo(tenant.ctx, owner.id, status=status)
        for status in ("open", "in_progress", "done", "done"):
            ap_db.add_todo(tenant.ctx, owner.id, status=status, deleted=True)
        values = collector.collect_tenant_metrics(tenant.id)
        check.equal(
            {key: values[key] for key in TODO_KEYS},
            {"todo_count": Decimal(9), "todo_open_count": Decimal(2), "todo_in_progress_count": Decimal(3), "todo_done_count": Decimal(4)},
        )
        check.equal(values["todo_open_count"] + values["todo_in_progress_count"] + values["todo_done_count"], values["todo_count"])

    def test_all_deleted_is_zero(self, ap_db, collector, metric_tenant):
        """すべて論理削除済みなら 0。"""
        tenant = metric_tenant()
        owner = seed_users(ap_db, tenant.ctx, active=1)[0]
        ap_db.add_todo(tenant.ctx, owner.id, deleted=True)
        values = collector.collect_tenant_metrics(tenant.id)
        check.equal([values[key] for key in TODO_KEYS], [Decimal(0)] * 4)

    def test_soft_deleting_changes_the_count(self, ap_db, collector, metric_tenant):
        """論理削除すると次の集計から数えない(現在の状態だけから求める)。"""
        tenant = metric_tenant()
        owner = seed_users(ap_db, tenant.ctx, active=1)[0]
        todo_id = ap_db.add_todo(tenant.ctx, owner.id)
        check.equal(collector.collect_tenant_metrics(tenant.id)["todo_count"], Decimal(1))
        with ap_db.session(tenant.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_todo SET deleted_at = now() WHERE id = %s", (todo_id,))
            session.commit()
        check.equal(collector.collect_tenant_metrics(tenant.id)["todo_count"], Decimal(0))

    def test_same_state_gives_same_values(self, ap_db, collector, metric_tenant):
        """同じ状態なら何度集計しても同じ値(日次スナップショットの冪等性の前提)。"""
        tenant = metric_tenant()
        owner = seed_users(ap_db, tenant.ctx, active=2)[0]
        ap_db.add_todo(tenant.ctx, owner.id, status="done")
        check.equal(collector.collect_tenant_metrics(tenant.id), collector.collect_tenant_metrics(tenant.id))


class TestRepositoryBehavior:
    """リポジトリ自体の振る舞い。"""

    def test_invalid_collector_result_raises(self, app_cp_agent_engine, metric_tenant):
        """集計関数が宣言と違うキーを返したら ValueError(誤った値を保存しない)。"""
        broken = TenantMetricSet(name="broken", keys=("x_count",), collect=lambda session, tenant_id: {"y_count": 1})
        repository = AppTenantMetricsRepository(engine_factory=lambda: app_cp_agent_engine, metric_sets=[broken])
        with pytest.raises(ValueError, match="returned keys"):
            repository.collect_tenant_metrics(metric_tenant().id)

    def test_uses_repeatable_read_read_only_transaction(self, app_cp_agent_engine, metric_tenant):
        """全指標を REPEATABLE READ の 1 トランザクションで集計し、GUC を集計するテナントに設定している。"""
        seen = []

        def collect(session, tenant_id):
            connection = session.connection()
            seen.append(
                (
                    connection.execute(text("SHOW transaction_isolation")).scalar_one(),
                    connection.execute(text("SELECT current_setting('app.current_tenant', true)")).scalar_one(),
                    connection.execute(text("SELECT txid_current_if_assigned()")).scalar_one(),
                )
            )
            return {"x_count": 1}

        probe = TenantMetricSet(name="probe", keys=("x_count",), collect=collect)
        repository = AppTenantMetricsRepository(engine_factory=lambda: app_cp_agent_engine, metric_sets=[probe])
        tenant = metric_tenant()
        repository.collect_tenant_metrics(tenant.id)
        check.equal(seen, [("repeatable read", str(tenant.id), None)])
