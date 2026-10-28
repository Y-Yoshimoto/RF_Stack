# -*- coding: utf-8 -*-
"""control_plane_app.repositories.app_tenant_data(CP から AP DB のテナントデータを物理削除する)のテスト。

``app_cp_agent``(SELECT / DELETE のみ・RLS 適用)で、対象テナントの行だけが消え、他テナントの行は残ることを
一時テーブル(``rls_table_factory``)で確認する。``app_db`` に接続できなければ skip。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from control_plane_app.repositories.app_tenant_data import AppTenantDataRepository, TenantDataPurgeStep, default_purge_steps, table_purge_step


@pytest.fixture
def repository_for(app_cp_agent_engine):
    """一時テーブル名のリストから、``app_cp_agent`` を使う削除リポジトリを作るファクトリ。"""

    def build(*table_names: str, extra_steps: list[TenantDataPurgeStep] | None = None) -> AppTenantDataRepository:
        steps = [table_purge_step(name) for name in table_names] + list(extra_steps or [])
        return AppTenantDataRepository(engine_factory=lambda: app_cp_agent_engine, steps=steps)

    return build


class TestPurgeTenantData:
    """対象テナントの行だけを削除する。"""

    def test_deletes_only_the_target_tenant(self, seeded_rls_table, repository_for, app_runtime_engine, tenant_a, tenant_b):
        """テナント A を削除すると A の 2 行が消え、B の 1 行は残る。戻り値はテーブルごとの削除件数。"""
        result = repository_for(seeded_rls_table.name).purge_tenant_data(tenant_a.tenant_id)
        check.equal(result, {seeded_rls_table.name: 2})
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), [])
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_is_idempotent(self, seeded_rls_table, repository_for, tenant_a):
        """同じテナントを再度削除しても成功し、0 件になる(失敗後の再実行で収束する)。"""
        repository = repository_for(seeded_rls_table.name)
        repository.purge_tenant_data(tenant_a.tenant_id)
        check.equal(repository.purge_tenant_data(tenant_a.tenant_id), {seeded_rls_table.name: 0})

    def test_unknown_tenant_deletes_nothing(self, seeded_rls_table, repository_for, app_runtime_engine, tenant_a, tenant_b):
        """存在しないテナント ID を指定しても、他のテナントの行は一切消えない。"""
        result = repository_for(seeded_rls_table.name).purge_tenant_data(uuid.uuid4())
        check.equal(result, {seeded_rls_table.name: 0})
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), ["a1", "a2"])
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_steps_run_in_order_in_one_transaction(self, rls_table_factory, repository_for, app_runtime_engine, tenant_a, tenant_b):
        """複数のテーブルは指定の順(子テーブルが先)に削除し、全体で 1 トランザクション。途中で失敗したら先のステップも元に戻す。"""
        first = rls_table_factory()
        second = rls_table_factory()
        for table in (first, second):
            table.insert(app_runtime_engine, tenant_a, "a1")
            table.insert(app_runtime_engine, tenant_b, "b1")
        order = []

        def failing(session, tenant_id):
            order.append("failing")
            raise RuntimeError("boom")

        repository = repository_for(first.name, extra_steps=[TenantDataPurgeStep(name="failing_step", purge=failing)])
        with pytest.raises(RuntimeError):
            repository.purge_tenant_data(tenant_a.tenant_id)
        check.equal(order, ["failing"])
        check.equal(first.titles(app_runtime_engine, tenant_a), ["a1"], "失敗したので A の行も消えていない(ロールバック)")
        # 全て成功すれば、順に削除される
        ok = repository_for(first.name, second.name)
        check.equal(ok.step_names, [first.name, second.name])
        check.equal(ok.purge_tenant_data(tenant_a.tenant_id), {first.name: 1, second.name: 1})
        check.equal(second.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_cp_agent_cannot_see_rows_without_tenant_guc(self, seeded_rls_table, app_cp_agent_engine):
        """前提: app_cp_agent も RLS の対象で、テナントを指定しなければ 0 件(RLS を迂回するロールではない)。"""
        with app_cp_agent_engine.begin() as connection:
            rows = connection.execute(text(f"SELECT title FROM {seeded_rls_table.qualified}")).all()
        check.equal(rows, [])

    def test_cp_agent_cannot_insert(self, rls_table, app_cp_agent_engine, tenant_a):
        """前提: app_cp_agent は SELECT / DELETE のみで、INSERT は拒否される(権限の最小化)。"""
        from modules.tenancy.db import apply_tenant_guc

        with pytest.raises(DBAPIError), app_cp_agent_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            connection.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'x')"), {"t": str(tenant_a.tenant_id)})


class TestConfiguration:
    """リポジトリの構成。"""

    def test_no_steps_means_no_connection(self):
        """削除ステップが無ければ DB に接続せず(エンジンの取得もせず)空の結果を返す。"""

        def forbidden():
            raise AssertionError("エンジンを取得してはならない")

        repository = AppTenantDataRepository(engine_factory=forbidden, steps=[])
        check.equal(repository.purge_tenant_data(uuid.uuid4()), {})
        check.equal(repository.step_names, [])

    def test_default_steps_follow_the_registered_tables(self, monkeypatch):
        """既定の削除ステップは TENANT_DATA_PURGE_TABLES の順に作られる(現時点では AP にテナントスコープのテーブルが無く空)。"""
        from control_plane_app.repositories import app_tenant_data

        monkeypatch.setattr(app_tenant_data, "TENANT_DATA_PURGE_TABLES", ("t_child", "t_parent"))
        check.equal([step.name for step in default_purge_steps()], ["t_child", "t_parent"])

    @pytest.mark.parametrize("name", ["", "T_Upper", "a b", "a;drop table x", "a.b.c", "1abc", "a-b", 'a"b', "../x", "t\n"])
    def test_invalid_table_names_are_rejected(self, name):
        """テーブル名は小文字の識別子だけ許可し、SQL を埋め込める名前は ValueError で拒否する。"""
        with pytest.raises(ValueError):
            table_purge_step(name)

    @pytest.mark.parametrize("name", ["t_todo", "public.t_todo", "_x1"])
    def test_valid_table_names(self, name):
        """通常のテーブル名・スキーマ修飾名は受け付ける。"""
        check.equal(table_purge_step(name).name, name)
