# -*- coding: utf-8 -*-
"""ToDo のコメント(``t_todo_comment``)とチェックリスト項目(``t_todo_checklist_item``)の RLS・権限の結合テスト(tenant-isolation §5.1)。

``test_50_rls_ap_tables.py`` と同じ観点を、リビジョン 0004 で追加した 2 テーブルで確認する: ENABLE / FORCE の両方が設定されている、
ポリシー ``tenant_isolation`` がある、GUC 無しは 0 件、各テナントは自分の行だけ、他テナントの tenant_id の INSERT / UPDATE は拒否、
他テナントの行は UPDATE / DELETE の対象にならない、``app_cp_agent`` は SELECT / DELETE のみ。使い捨てのテナントを使い、alpha / beta には触れない。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from main_app.models import TTodo, TTodoChecklistItem, TTodoComment
from modules.tenancy.db import apply_tenant_guc

TABLES = ("t_todo_comment", "t_todo_checklist_item")


@pytest.fixture
def seeded(ap_db):
    """テナント A / B に、ユーザー・ToDo・コメント・チェックリスト項目を 1 つずつ作る。"""
    result = []
    for ctx in (ap_db.tenant(), ap_db.tenant()):
        user = ap_db.add_user(ctx)
        with ap_db.session(ctx) as session:
            todo = TTodo(tenant_id=ctx.tenant_id, created_by=user.id, updated_by=user.id, title="t")
            session.add(todo)
            session.flush()
            session.add(TTodoComment(tenant_id=ctx.tenant_id, todo_id=todo.id, author_id=user.id, body="c"))
            session.add(TTodoChecklistItem(tenant_id=ctx.tenant_id, todo_id=todo.id, title="i", position=0, created_by=user.id, updated_by=user.id))
            session.commit()
            result.append((ctx, user.id, todo.id))
    return result


def count(engine, table: str, tenant_id: uuid.UUID | None) -> int:
    """指定の GUC(None は未設定)での、テーブルの見える行数。"""
    with engine.begin() as connection:
        if tenant_id is not None:
            apply_tenant_guc(connection, tenant_id)
        return int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())


@pytest.mark.parametrize("table", TABLES)
def test_rls_is_enabled_and_forced_with_the_standard_policy(ap_db, table):
    """ENABLE と FORCE の両方が設定され、ポリシー tenant_isolation(USING / WITH CHECK が app.current_tenant)がある。"""
    with ap_db.runtime.connect() as connection:
        flags = connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t AND relnamespace = 'public'::regnamespace"), {"t": table}).one()
        policies = connection.execute(text("SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = :t"), {"t": table}).all()
    check.equal(tuple(flags), (True, True))
    check.equal([p[0] for p in policies], ["tenant_isolation"])
    for expression in policies[0][1:]:
        check.is_true("app.current_tenant" in expression and "tenant_id" in expression, expression)


@pytest.mark.parametrize("table", TABLES)
def test_tenant_id_is_not_null_and_indexed(ap_db, table):
    """tenant_id は NOT NULL で、tenant_id 先頭のインデックスがある。"""
    with ap_db.runtime.connect() as connection:
        nullable = connection.execute(text("SELECT is_nullable FROM information_schema.columns WHERE table_name = :t AND column_name = 'tenant_id'"), {"t": table}).scalar_one()
        indexes = connection.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename = :t"), {"t": table}).scalars().all()
    check.equal(nullable, "NO")
    check.is_true(any("(tenant_id)" in definition or "(tenant_id, " in definition for definition in indexes), indexes)


@pytest.mark.parametrize("table", TABLES)
def test_no_context_sees_nothing(ap_db, seeded, table):
    """コンテキスト(GUC)無しの app_runtime は 0 件(エラーにならず空になる)。"""
    check.equal(count(ap_db.runtime, table, None), 0)


@pytest.mark.parametrize("table", TABLES)
def test_each_tenant_sees_only_own_rows(ap_db, seeded, table):
    """各テナントのコンテキストでは自分の 1 行だけが見え、無関係のテナントでは 0 件。"""
    (a, _, _), (b, _, _) = seeded
    check.equal((count(ap_db.runtime, table, a.tenant_id), count(ap_db.runtime, table, b.tenant_id), count(ap_db.runtime, table, uuid.uuid4())), (1, 1, 0))


@pytest.mark.parametrize("table", TABLES)
def test_cp_agent_without_guc_sees_nothing_and_with_guc_sees_one_tenant(ap_db, seeded, table):
    """app_cp_agent も RLS の対象で、GUC 無しは 0 件、テナントを切り替えるとそのテナントの行だけが見える。"""
    (a, _, _), (b, _, _) = seeded
    check.equal((count(ap_db.agent, table, None), count(ap_db.agent, table, a.tenant_id), count(ap_db.agent, table, b.tenant_id)), (0, 1, 1))


def test_cross_tenant_reads_through_the_service_layer_are_empty(ap_db, seeded):
    """サービス層(ORM)の経路でも、A のコンテキストでは B のコメント・項目の ID を指定しても取得できない。"""
    (a, _, _), (b, _, b_todo) = seeded
    b_comment = ap_db.rows(b, "SELECT id FROM t_todo_comment")[0]["id"]
    b_item = ap_db.rows(b, "SELECT id FROM t_todo_checklist_item")[0]["id"]
    with ap_db.session(a) as session:
        check.is_none(session.get(TTodoComment, b_comment))
        check.is_none(session.get(TTodoChecklistItem, b_item))
        check.equal(session.connection().execute(text("SELECT count(*) FROM t_todo_comment WHERE todo_id = :t"), {"t": b_todo}).scalar_one(), 0)


def test_insert_with_other_tenant_id_is_rejected(ap_db, seeded):
    """GUC と違う tenant_id を書いた INSERT は、RLS の WITH CHECK で拒否される(コメント・項目とも)。他テナントの行は増えない。"""
    (a, a_user, a_todo), (b, b_user, b_todo) = seeded
    rows = [
        TTodoComment(tenant_id=b.tenant_id, todo_id=b_todo, author_id=b_user, body="x"),
        TTodoChecklistItem(tenant_id=b.tenant_id, todo_id=b_todo, title="x", position=1, created_by=b_user, updated_by=b_user),
    ]
    for row in rows:
        with ap_db.session(a) as session:
            session.add(row)
            with pytest.raises(DBAPIError):
                session.commit()
    check.equal([count(ap_db.runtime, table, b.tenant_id) for table in TABLES], [1, 1])


def test_update_and_delete_of_other_tenant_rows_affect_nothing(ap_db, seeded):
    """他テナントの行は UPDATE / DELETE の対象にならない(0 行。エラーにもならない)。"""
    (a, _, _), (b, _, b_todo) = seeded
    with ap_db.runtime.begin() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        results = [
            connection.execute(text("UPDATE t_todo_comment SET body = 'hacked' WHERE tenant_id = :t"), {"t": b.tenant_id}).rowcount,
            connection.execute(text("UPDATE t_todo_checklist_item SET title = 'hacked' WHERE tenant_id = :t"), {"t": b.tenant_id}).rowcount,
            connection.execute(text("DELETE FROM t_todo_comment WHERE tenant_id = :t"), {"t": b.tenant_id}).rowcount,
            connection.execute(text("DELETE FROM t_todo_checklist_item WHERE todo_id = :t"), {"t": b_todo}).rowcount,
        ]
    check.equal(results, [0, 0, 0, 0])
    check.equal([r["body"] for r in ap_db.rows(b, "SELECT body FROM t_todo_comment")], ["c"])
    check.equal([r["title"] for r in ap_db.rows(b, "SELECT title FROM t_todo_checklist_item")], ["i"])


@pytest.mark.parametrize("table", TABLES)
def test_changing_tenant_id_of_own_row_is_rejected(ap_db, seeded, table):
    """自分の行の tenant_id を他テナントに書き換える UPDATE は拒否される(WITH CHECK)。"""
    (a, _, _), (b, _, _) = seeded
    with ap_db.runtime.begin() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        with pytest.raises(DBAPIError):
            connection.execute(text(f"UPDATE {table} SET tenant_id = :b WHERE tenant_id = :a"), {"a": a.tenant_id, "b": b.tenant_id})
    check.equal(count(ap_db.runtime, table, a.tenant_id), 1)


def test_runtime_can_write_own_rows(ap_db, seeded):
    """app_runtime は自テナントの行を INSERT / UPDATE / DELETE できる(物理削除はチェックリスト項目のみ使う)。"""
    (a, a_user, a_todo), _ = seeded
    with ap_db.runtime.begin() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        connection.execute(text("UPDATE t_todo_comment SET body = 'edited', version = version + 1 WHERE tenant_id = :t"), {"t": a.tenant_id})
        connection.execute(text("DELETE FROM t_todo_checklist_item WHERE tenant_id = :t"), {"t": a.tenant_id})
    check.equal(([r["body"] for r in ap_db.rows(a, "SELECT body FROM t_todo_comment")], count(ap_db.runtime, "t_todo_checklist_item", a.tenant_id)), (["edited"], 0))


def test_cp_agent_cannot_write_but_can_delete(ap_db, seeded):
    """app_cp_agent は SELECT / DELETE のみ。INSERT / UPDATE はできず(CP から AP へ書き込まない。05 #31)、DELETE(物理削除)はできる。"""
    (a, a_user, a_todo), _ = seeded
    statements = [
        ("UPDATE t_todo_comment SET body = 'by-agent' WHERE tenant_id = :t", {"t": a.tenant_id}),
        ("UPDATE t_todo_checklist_item SET title = 'by-agent' WHERE tenant_id = :t", {"t": a.tenant_id}),
        ("INSERT INTO t_todo_comment (tenant_id, todo_id, author_id, body) VALUES (:t, :todo, :u, 'x')", {"t": a.tenant_id, "todo": a_todo, "u": a_user}),
    ]
    for statement, params in statements:
        with ap_db.agent.connect() as connection:
            apply_tenant_guc(connection, a.tenant_id)
            with pytest.raises(ProgrammingError):
                connection.execute(text(statement), params)
            connection.rollback()
    check.equal([r["body"] for r in ap_db.rows(a, "SELECT body FROM t_todo_comment")], ["c"])
    with ap_db.agent.begin() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        deleted = [connection.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": a.tenant_id}).rowcount for table in TABLES]
    check.equal(deleted, [1, 1])


def test_comment_timestamps_have_timezone(ap_db, seeded):
    """日時の列は timestamptz(コメントの created_at / edited_at / deleted_at、項目の done_at)。"""
    with ap_db.runtime.connect() as connection:
        types = dict(
            connection.execute(
                text(
                    "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
                    "WHERE (table_name, column_name) IN (('t_todo_comment','created_at'),('t_todo_comment','edited_at'),('t_todo_comment','deleted_at'),('t_todo_checklist_item','done_at'))"
                )
            ).all()
        )
    check.equal(set(types.values()), {"timestamp with time zone"})
    check.equal(len(types), 4)
