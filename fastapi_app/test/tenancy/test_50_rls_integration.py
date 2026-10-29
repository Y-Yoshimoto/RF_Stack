# -*- coding: utf-8 -*-
"""RLS 結合テスト(app_db。``app_owner`` で一時テーブルを作り、``app_runtime`` で検証する)。

DB に接続できない・ロールが無い環境ではスキップされる(フィクスチャは ``conftest.py``)。
今後のテーマ別クロステナントテストは、このファイルの書き方(フィクスチャの使い方)を雛形にする。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from modules.tenancy.context import tenant_scope
from modules.tenancy.db import apply_tenant_guc, get_tenant_guc, install_tenant_guc_listener, run_per_tenant, tenant_guc_scope, uninstall_tenant_guc_listener
from modules.tenancy.rls import build_disable_tenant_rls_sql

RLS_VIOLATION = "row-level security"


def _pgcode(exc_info) -> str | None:
    """psycopg2 の SQLSTATE を取り出す。"""
    return getattr(exc_info.value.orig, "pgcode", None)


class TestVisibility:
    """app_runtime のテナント切り替えによる可視性。"""

    def test_each_tenant_sees_only_own_rows(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """テナント A は a1/a2 のみ、B は b1 のみ見える。"""
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), ["a1", "a2"])
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_switching_tenant_on_same_connection_changes_view(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """同じ接続・同じトランザクションでも GUC を切り替えれば見える行が切り替わる。"""
        with app_runtime_engine.begin() as connection:
            counts = []
            for tenant in (tenant_a, tenant_b, tenant_a):
                apply_tenant_guc(connection, tenant.tenant_id)
                counts.append(connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}")).scalar())
        check.equal(counts, [2, 1, 2])

    def test_unknown_tenant_sees_nothing(self, seeded_rls_table, app_runtime_engine):
        """どの行にも属さないテナントでは 0 件。"""
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, uuid.uuid4())
            check.equal(connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}")).scalar(), 0)

    def test_without_guc_returns_zero_rows_not_error(self, seeded_rls_table, app_runtime_engine):
        """GUC 未設定ならエラーではなく 0 件(気づきにくいので回帰テストで固定)。"""
        check.equal(seeded_rls_table.titles(app_runtime_engine, None), [])

    def test_empty_guc_returns_zero_rows(self, seeded_rls_table, app_runtime_engine):
        """apply_tenant_guc(None) の空文字でも 0 件。"""
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, None)
            check.is_none(get_tenant_guc(connection))
            check.equal(connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}")).scalar(), 0)

    def test_malformed_guc_fails_closed(self, seeded_rls_table, app_runtime_engine):
        """GUC が UUID でない値なら、行は見えず(キャスト失敗でエラー)、他テナントが見えることはない。"""
        with pytest.raises(DBAPIError):
            with app_runtime_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.current_tenant', 'not-a-uuid', true)"))
                connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}"))

    def test_filter_by_other_tenant_id_still_hidden(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """WHERE で他テナントの tenant_id を指定しても RLS で 0 件(アプリが tenant_id を信用しても漏れない)。"""
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            rows = connection.execute(text(f"SELECT title FROM {seeded_rls_table.qualified} WHERE tenant_id = :t"), {"t": str(tenant_b.tenant_id)}).all()
        check.equal(rows, [])


class TestWriteChecks:
    """WITH CHECK による書き込みの拒否。"""

    def test_insert_for_other_tenant_is_rejected(self, rls_table, app_runtime_engine, tenant_a, tenant_b):
        """テナント A のコンテキストで tenant_id=B の INSERT は RLS 違反(42501)。"""
        with pytest.raises(ProgrammingError) as exc_info:
            with app_runtime_engine.begin() as connection:
                apply_tenant_guc(connection, tenant_a.tenant_id)
                connection.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'x')"), {"t": str(tenant_b.tenant_id)})
        check.equal(_pgcode(exc_info), "42501")
        check.is_in(RLS_VIOLATION, str(exc_info.value.orig))

    def test_insert_without_guc_is_rejected(self, rls_table, app_runtime_engine, tenant_a):
        """GUC 未設定での INSERT は拒否される。"""
        with pytest.raises(ProgrammingError) as exc_info:
            with app_runtime_engine.begin() as connection:
                connection.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'x')"), {"t": str(tenant_a.tenant_id)})
        check.is_in(RLS_VIOLATION, str(exc_info.value.orig))

    def test_update_changing_tenant_id_is_rejected(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """自テナントの行の tenant_id を他テナントに書き換える UPDATE は拒否され、行は変わらない。"""
        with pytest.raises(ProgrammingError) as exc_info:
            with app_runtime_engine.begin() as connection:
                apply_tenant_guc(connection, tenant_a.tenant_id)
                connection.execute(text(f"UPDATE {seeded_rls_table.qualified} SET tenant_id = :b WHERE title = 'a1'"), {"b": str(tenant_b.tenant_id)})
        check.is_in(RLS_VIOLATION, str(exc_info.value.orig))
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), ["a1", "a2"])
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_update_other_tenant_rows_affects_nothing(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """他テナントの行への UPDATE は 0 行(エラーにならない)で、B のデータは変わらない。"""
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            result = connection.execute(text(f"UPDATE {seeded_rls_table.qualified} SET title = 'hacked' WHERE title = 'b1'"))
            check.equal(result.rowcount, 0)
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_delete_other_tenant_rows_affects_nothing(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """他テナントの行への DELETE は 0 行で、B のデータは残る。"""
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            check.equal(connection.execute(text(f"DELETE FROM {seeded_rls_table.qualified}")).rowcount, 2, "自テナントの行だけが消える")
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), [])

    def test_own_tenant_insert_update_delete_succeed(self, rls_table, app_runtime_engine, tenant_a):
        """自テナントの INSERT / UPDATE / DELETE は成功する(RLS が正常系を壊していない)。"""
        rls_table.insert(app_runtime_engine, tenant_a, "t1")
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            check.equal(connection.execute(text(f"UPDATE {rls_table.qualified} SET title = 't2'")).rowcount, 1)
        check.equal(rls_table.titles(app_runtime_engine, tenant_a), ["t2"])
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            check.equal(connection.execute(text(f"DELETE FROM {rls_table.qualified}")).rowcount, 1)


class TestForceRls:
    """所有者(app_owner)にも FORCE ROW LEVEL SECURITY が効く。"""

    def test_owner_is_subject_to_rls(self, seeded_rls_table, app_owner_engine, tenant_a, tenant_b):
        """app_owner も GUC 未設定なら 0 件、設定すればそのテナントの行だけ見える。"""
        check.equal(seeded_rls_table.titles(app_owner_engine, None), [])
        check.equal(seeded_rls_table.titles(app_owner_engine, tenant_a), ["a1", "a2"])
        check.equal(seeded_rls_table.titles(app_owner_engine, tenant_b), ["b1"])

    def test_owner_cannot_insert_for_other_tenant(self, seeded_rls_table, app_owner_engine, tenant_a, tenant_b):
        """app_owner でも WITH CHECK に違反する INSERT は拒否される。"""
        with pytest.raises(ProgrammingError) as exc_info:
            with app_owner_engine.begin() as connection:
                apply_tenant_guc(connection, tenant_a.tenant_id)
                connection.execute(text(f"INSERT INTO {seeded_rls_table.qualified} (tenant_id, title) VALUES (:t, 'x')"), {"t": str(tenant_b.tenant_id)})
        check.is_in(RLS_VIOLATION, str(exc_info.value.orig))

    def test_negative_control_owner_sees_all_without_force(self, seeded_rls_table, app_owner_engine):
        """(対照実験)FORCE を外すと所有者は全行を見る。上のテストが FORCE のおかげで成立していることの確認。"""
        table = seeded_rls_table.qualified
        with app_owner_engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
            check.equal(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar(), 3)

    def test_without_rls_all_rows_visible_negative_control(self, rls_table_factory, app_runtime_engine, tenant_a, tenant_b):
        """(対照実験)RLS を適用していないテーブルでは他テナントの行が見える。RLS 適用忘れを検知するテストの有効性確認。"""
        table = rls_table_factory(apply_rls=False)
        table.insert(app_runtime_engine, tenant_a, "a1")
        table.insert(app_runtime_engine, tenant_b, "b1")
        check.equal(table.titles(app_runtime_engine, tenant_a), ["a1", "b1"])

    def test_disable_sql_restores_unprotected_state(self, seeded_rls_table, app_owner_engine, app_runtime_engine, tenant_a):
        """build_disable_tenant_rls_sql を実行すると保護が外れる(downgrade の動作確認)。"""
        with app_owner_engine.begin() as connection:
            for statement in build_disable_tenant_rls_sql(seeded_rls_table.name, schema=seeded_rls_table.schema):
                connection.execute(text(statement))
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), ["a1", "a2", "b1"])

    def test_catalog_flags(self, rls_table, app_owner_engine):
        """pg_class 上で relrowsecurity と relforcerowsecurity の両方が true、ポリシーは tenant_isolation。"""
        with app_owner_engine.connect() as connection:
            flags = connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = CAST(:q AS regclass)"), {"q": rls_table.qualified}).one()
            policies = connection.execute(text("SELECT policyname FROM pg_policies WHERE tablename = :n"), {"n": rls_table.name}).scalars().all()
        check.equal(tuple(flags), (True, True))
        check.equal(list(policies), ["tenant_isolation"])

    def test_runtime_roles_cannot_bypass_rls(self, app_owner_engine):
        """app 系ロールは SUPERUSER でも BYPASSRLS でもない(RLS をバイパスするロールを作らない)。"""
        with app_owner_engine.connect() as connection:
            rows = connection.execute(text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = ANY(:names)"), {"names": ["app_owner", "app_runtime", "app_cp_agent"]}).all()
        check.greater_equal(len(rows), 1)
        for name, is_super, bypass in rows:
            check.is_false(is_super, name)
            check.is_false(bypass, name)


class TestCompositeForeignKey:
    """複合外部キーが DB でもテナント跨ぎの関連付けを拒否する。"""

    def test_cross_tenant_reference_rejected_by_fk(self, rls_table_factory, app_runtime_engine, tenant_a, tenant_b):
        """親が B、子が A のときの参照は、RLS で親が見えなくても FK 自体が拒否する。同一テナントなら成功する。"""
        parent = rls_table_factory(extra_ddl="UNIQUE (tenant_id, id)")
        child = rls_table_factory(extra_ddl=f"parent_id uuid, FOREIGN KEY (tenant_id, parent_id) REFERENCES {parent.qualified} (tenant_id, id)")
        parent.insert(app_runtime_engine, tenant_a, "parent-a")
        parent.insert(app_runtime_engine, tenant_b, "parent-b")

        def parent_id(tenant) -> str:
            with app_runtime_engine.begin() as connection:
                apply_tenant_guc(connection, tenant.tenant_id)
                return str(connection.execute(text(f"SELECT id FROM {parent.qualified}")).scalar_one())

        sql = f"INSERT INTO {child.qualified} (tenant_id, title, parent_id) VALUES (:t, 'c', :p)"
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            connection.execute(text(sql), {"t": str(tenant_a.tenant_id), "p": parent_id(tenant_a)})  # 同一テナント: 成功
        with pytest.raises(DBAPIError) as exc_info:
            with app_runtime_engine.begin() as connection:
                apply_tenant_guc(connection, tenant_a.tenant_id)
                connection.execute(text(sql), {"t": str(tenant_a.tenant_id), "p": parent_id(tenant_b)})  # A の子が B の親を参照
        check.equal(_pgcode(exc_info), "23503")  # foreign_key_violation


class TestGucDoesNotLeakThroughPool:
    """トランザクションスコープの GUC がプールの再利用接続に残らない。"""

    def _backend_pid(self, connection) -> int:
        return connection.execute(text("SELECT pg_backend_pid()")).scalar_one()

    @pytest.mark.parametrize("finish", ["commit", "rollback"])
    def test_reused_connection_has_no_guc(self, seeded_rls_table, single_connection_runtime_engine, tenant_a, finish):
        """プール 1 本で同じ物理接続を再利用しても、前のトランザクションの GUC は消えており 0 件になる。"""
        engine = single_connection_runtime_engine
        with engine.connect() as connection:
            first_pid = self._backend_pid(connection)
            apply_tenant_guc(connection, tenant_a.tenant_id)
            check.equal(connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}")).scalar(), 2)
            getattr(connection, finish)()
        with engine.connect() as connection:
            check.equal(self._backend_pid(connection), first_pid, "同じ物理接続が再利用されている")
            check.is_none(get_tenant_guc(connection))
            check.equal(connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}")).scalar(), 0)

    def test_guc_is_reverted_by_savepoint_rollback(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """SAVEPOINT 内で設定した GUC は SAVEPOINT のロールバックで巻き戻る。"""
        with app_runtime_engine.begin() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            savepoint = connection.begin_nested()
            apply_tenant_guc(connection, tenant_b.tenant_id)
            check.equal(get_tenant_guc(connection), tenant_b.tenant_id)
            savepoint.rollback()
            check.equal(get_tenant_guc(connection), tenant_a.tenant_id)

    def test_guc_cleared_after_commit_in_same_connection(self, app_runtime_engine, tenant_a):
        """COMMIT 後の同じ接続で、新しいトランザクションの GUC は未設定。"""
        with app_runtime_engine.connect() as connection:
            apply_tenant_guc(connection, tenant_a.tenant_id)
            connection.commit()
            check.is_none(get_tenant_guc(connection))


class TestTenantGucScope:
    """tenant_guc_scope(1 トランザクション内のテナント切り替え)。"""

    def test_switches_and_restores(self, seeded_rls_table, app_runtime_engine, tenant_a, tenant_b):
        """スコープ内は指定テナント、抜けると元の GUC に戻る。入れ子も元に戻る。"""
        with app_runtime_engine.begin() as connection:
            check.is_none(get_tenant_guc(connection))
            with tenant_guc_scope(connection, tenant_a.tenant_id):
                check.equal(get_tenant_guc(connection), tenant_a.tenant_id)
                with tenant_guc_scope(connection, tenant_b.tenant_id):
                    check.equal(get_tenant_guc(connection), tenant_b.tenant_id)
                check.equal(get_tenant_guc(connection), tenant_a.tenant_id)
            check.is_none(get_tenant_guc(connection))

    def test_exception_is_propagated_and_rolled_back(self, seeded_rls_table, app_runtime_engine, tenant_a):
        """ブロック内の例外は再送出され、ロールバックで GUC も消える(戻し処理は走らせない設計)。"""
        with pytest.raises(RuntimeError, match="boom"):
            with app_runtime_engine.begin() as connection:
                with tenant_guc_scope(connection, tenant_a.tenant_id):
                    raise RuntimeError("boom")
        with app_runtime_engine.connect() as connection:
            check.is_none(get_tenant_guc(connection))

    def test_session_flushes_before_switch(self, rls_table, app_runtime_engine, tenant_a, tenant_b):
        """Session では切り替え前に flush するため、A で追加した行は A として書き込まれる。"""
        with Session(app_runtime_engine) as session, session.begin():
            with tenant_guc_scope(session, tenant_a.tenant_id):
                session.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'a-row')"), {"t": str(tenant_a.tenant_id)})
            with tenant_guc_scope(session, tenant_b.tenant_id):
                session.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'b-row')"), {"t": str(tenant_b.tenant_id)})
                visible = session.execute(text(f"SELECT title FROM {rls_table.qualified}")).scalars().all()
                check.equal(list(visible), ["b-row"])
        check.equal(rls_table.titles(app_runtime_engine, tenant_a), ["a-row"])
        check.equal(rls_table.titles(app_runtime_engine, tenant_b), ["b-row"])


class TestCpAgent:
    """app_cp_agent: テナント毎にコンテキストを切り替えて SELECT / DELETE のみ可能。"""

    def test_run_per_tenant_counts(self, seeded_rls_table, app_cp_agent_engine, tenant_a, tenant_b):
        """run_per_tenant でテナント毎の件数を集計できる(RLS をバイパスせず、各テナントの行だけ)。"""
        with app_cp_agent_engine.begin() as connection:
            counts = run_per_tenant(connection, [tenant_a.tenant_id, tenant_b.tenant_id], lambda _tid: connection.execute(text(f"SELECT count(*) FROM {seeded_rls_table.qualified}")).scalar_one())
        check.equal(counts, {tenant_a.tenant_id: 2, tenant_b.tenant_id: 1})

    def test_without_scope_sees_nothing(self, seeded_rls_table, app_cp_agent_engine):
        """コンテキストなしの app_cp_agent は 0 件(横断的に見える経路はない)。"""
        check.equal(seeded_rls_table.titles(app_cp_agent_engine, None), [])

    def test_delete_one_tenant_via_scope(self, seeded_rls_table, app_cp_agent_engine, app_runtime_engine, tenant_a, tenant_b):
        """tenant_guc_scope で指定したテナントの行だけ DELETE でき、他テナントは残る(物理削除)。"""
        with app_cp_agent_engine.begin() as connection:
            with tenant_guc_scope(connection, tenant_a.tenant_id):
                check.equal(connection.execute(text(f"DELETE FROM {seeded_rls_table.qualified}")).rowcount, 2)
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_a), [])
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), ["b1"])

    def test_run_per_tenant_delete_all(self, seeded_rls_table, app_cp_agent_engine, app_runtime_engine, tenant_a, tenant_b):
        """run_per_tenant で全テナント分を削除し、削除件数を返せる。"""
        with app_cp_agent_engine.begin() as connection:
            deleted = run_per_tenant(connection, [tenant_a.tenant_id, tenant_b.tenant_id], lambda _tid: connection.execute(text(f"DELETE FROM {seeded_rls_table.qualified}")).rowcount)
        check.equal(deleted, {tenant_a.tenant_id: 2, tenant_b.tenant_id: 1})
        check.equal(seeded_rls_table.titles(app_runtime_engine, tenant_b), [])

    def test_insert_is_denied(self, seeded_rls_table, app_cp_agent_engine, tenant_a):
        """app_cp_agent は INSERT できない(テーブル権限なし。42501)。"""
        with pytest.raises(ProgrammingError) as exc_info:
            with app_cp_agent_engine.begin() as connection:
                with tenant_guc_scope(connection, tenant_a.tenant_id):
                    connection.execute(text(f"INSERT INTO {seeded_rls_table.qualified} (tenant_id, title) VALUES (:t, 'x')"), {"t": str(tenant_a.tenant_id)})
        check.equal(_pgcode(exc_info), "42501")
        check.is_in("permission denied", str(exc_info.value.orig))

    def test_update_is_denied(self, seeded_rls_table, app_cp_agent_engine, tenant_a):
        """app_cp_agent は UPDATE もできない。"""
        with pytest.raises(ProgrammingError) as exc_info:
            with app_cp_agent_engine.begin() as connection:
                with tenant_guc_scope(connection, tenant_a.tenant_id):
                    connection.execute(text(f"UPDATE {seeded_rls_table.qualified} SET title = 'x'"))
        check.equal(_pgcode(exc_info), "42501")

    def test_run_per_tenant_stops_on_error(self, seeded_rls_table, app_cp_agent_engine, tenant_a, tenant_b):
        """途中で例外が出たら以降のテナントは処理せず再送出する。"""
        visited: list[uuid.UUID] = []

        def func(tenant_id: uuid.UUID) -> int:
            visited.append(tenant_id)
            raise RuntimeError("stop")

        with pytest.raises(RuntimeError, match="stop"):
            with app_cp_agent_engine.begin() as connection:
                run_per_tenant(connection, [tenant_a.tenant_id, tenant_b.tenant_id], func)
        check.equal(visited, [tenant_a.tenant_id])


class TestGucListener:
    """install_tenant_guc_listener による自動適用。"""

    @pytest.fixture
    def session_factory(self, app_runtime_engine):
        """リスナー登録済みの sessionmaker(終了時に解除)。"""
        factory = sessionmaker(bind=app_runtime_engine)
        install_tenant_guc_listener(factory)
        try:
            yield factory
        finally:
            uninstall_tenant_guc_listener(factory)

    def _titles(self, session, table) -> list[str]:
        return sorted(session.execute(text(f"SELECT title FROM {table.qualified}")).scalars().all())

    def test_context_is_applied_automatically(self, seeded_rls_table, session_factory, tenant_a, tenant_b):
        """tenant_scope の中で開始したセッションには、そのテナントの GUC が自動で入る。"""
        with tenant_scope(tenant_a), session_factory() as session:
            check.equal(self._titles(session, seeded_rls_table), ["a1", "a2"])
            check.equal(get_tenant_guc(session), tenant_a.tenant_id)
        with tenant_scope(tenant_b), session_factory() as session:
            check.equal(self._titles(session, seeded_rls_table), ["b1"])

    def test_without_context_sees_nothing(self, seeded_rls_table, session_factory):
        """コンテキストなしで開始したセッションは 0 件(エラーにはならない)。"""
        with session_factory() as session:
            check.equal(self._titles(session, seeded_rls_table), [])
            check.is_none(get_tenant_guc(session))

    def test_insert_through_session_uses_context_tenant(self, rls_table, session_factory, app_runtime_engine, tenant_a, tenant_b):
        """自動適用された GUC で INSERT でき、他テナント宛の INSERT は WITH CHECK で拒否される。"""
        with tenant_scope(tenant_a), session_factory() as session, session.begin():
            session.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'mine')"), {"t": str(tenant_a.tenant_id)})
        with pytest.raises(ProgrammingError):
            with tenant_scope(tenant_a), session_factory() as session, session.begin():
                session.execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'theirs')"), {"t": str(tenant_b.tenant_id)})
        check.equal(rls_table.titles(app_runtime_engine, tenant_a), ["mine"])
        check.equal(rls_table.titles(app_runtime_engine, tenant_b), [])

    def test_each_transaction_reads_current_context(self, seeded_rls_table, session_factory, tenant_a, tenant_b):
        """同じセッションでも COMMIT 後の次のトランザクションは、その時点のコンテキストを反映する。"""
        with session_factory() as session:
            with tenant_scope(tenant_a):
                check.equal(self._titles(session, seeded_rls_table), ["a1", "a2"])
                session.commit()
            with tenant_scope(tenant_b):
                check.equal(self._titles(session, seeded_rls_table), ["b1"])
                session.commit()
            check.equal(self._titles(session, seeded_rls_table), [], "コンテキストなしの次のトランザクションは 0 件")

    def test_switching_context_mid_transaction_is_not_reflected(self, seeded_rls_table, session_factory, tenant_a, tenant_b):
        """トランザクション開始後にコンテキストを変えても GUC は変わらない(文書化された制約。途中切替は tenant_guc_scope を使う)。"""
        with tenant_scope(tenant_a), session_factory() as session:
            check.equal(self._titles(session, seeded_rls_table), ["a1", "a2"])
            with tenant_scope(tenant_b):
                check.equal(self._titles(session, seeded_rls_table), ["a1", "a2"])

    def test_guc_does_not_leak_to_next_session_on_pooled_connection(self, seeded_rls_table, single_connection_runtime_engine, tenant_a):
        """リスナー付きでプール 1 本を使い回しても、コンテキストなしのセッションに前のテナントが残らない。"""
        factory = sessionmaker(bind=single_connection_runtime_engine)
        install_tenant_guc_listener(factory)
        try:
            with tenant_scope(tenant_a), factory() as session:
                check.equal(self._titles(session, seeded_rls_table), ["a1", "a2"])
            with factory() as session:
                check.equal(self._titles(session, seeded_rls_table), [])
        finally:
            uninstall_tenant_guc_listener(factory)

    def test_listener_registered_on_one_factory_does_not_affect_another(self, seeded_rls_table, session_factory, app_runtime_engine, tenant_a):
        """リスナーは登録した sessionmaker だけに効き、別の sessionmaker には効かない(Session クラス全体に登録しない理由)。"""
        other = sessionmaker(bind=app_runtime_engine)
        with tenant_scope(tenant_a), other() as session:
            check.equal(self._titles(session, seeded_rls_table), [])
