# -*- coding: utf-8 -*-
"""AP 共通テーブル(t_user / t_organization / t_organization_member / t_ap_audit_log)の RLS・権限・複合外部キーの結合テスト。

``tenancy`` の RLS 結合テストは一時テーブルで一般的な振る舞いを確認している。ここでは実際のテーブルで、テナントスコープのテーブルを
追加/変更したときの確認項目(tenant-isolation §5.1)を確認する。使い捨てのテナントを使い、終了時に削除する。alpha / beta には触れない。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlmodel import Session

from main_app.models import TApAuditLog, TOrganization, TUser
from modules.tenancy.db import apply_tenant_guc

TABLES = ("t_user", "t_organization", "t_organization_member", "t_ap_audit_log")


@pytest.fixture
def seeded(ap_db):
    """テナント A / B に、ユーザー・組織(所属付き)・監査ログを 1 つずつ作る。"""
    a, b = ap_db.tenant(), ap_db.tenant()
    for ctx in (a, b):
        user = ap_db.add_user(ctx)
        ap_db.add_org(ctx, f"org-{ctx.tenant_code}", members=(user.id,))
        with ap_db.session(ctx) as session:
            session.add(TApAuditLog(tenant_id=ctx.tenant_id, action="test.seed", target_type="user", target_id=str(user.id)))
            session.commit()
    return a, b


def count(engine, table: str, tenant_id: uuid.UUID | None) -> int:
    """指定の GUC(None は未設定)での、テーブルの見える行数。"""
    with engine.begin() as connection:
        if tenant_id is not None:
            apply_tenant_guc(connection, tenant_id)
        return int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())


@pytest.mark.parametrize("table", TABLES)
def test_no_context_sees_nothing(ap_db, seeded, table):
    """コンテキスト(GUC)無しの app_runtime は、どのテーブルも 0 件(エラーにならず空になる)。"""
    check.equal(count(ap_db.runtime, table, None), 0)


@pytest.mark.parametrize("table", TABLES)
def test_each_tenant_sees_only_own_rows(ap_db, seeded, table):
    """各テナントのコンテキストでは、自分の 1 行だけが見える(他テナントの行は件数にも現れない)。"""
    a, b = seeded
    check.equal((count(ap_db.runtime, table, a.tenant_id), count(ap_db.runtime, table, b.tenant_id), count(ap_db.runtime, table, uuid.uuid4())), (1, 1, 0))


@pytest.mark.parametrize("table", TABLES)
def test_cp_agent_without_guc_sees_nothing_and_with_guc_sees_one_tenant(ap_db, seeded, table):
    """app_cp_agent も RLS の対象で、GUC 無しは 0 件、テナントを切り替えるとそのテナントの行だけが見える。"""
    a, b = seeded
    check.equal((count(ap_db.agent, table, None), count(ap_db.agent, table, a.tenant_id), count(ap_db.agent, table, b.tenant_id)), (0, 1, 1))


def test_insert_with_other_tenant_id_is_rejected(ap_db, seeded):
    """GUC と違う tenant_id を書いた INSERT は、RLS の WITH CHECK で拒否される(t_user / t_organization / t_ap_audit_log)。"""
    a, b = seeded
    rows = [
        TUser(tenant_id=b.tenant_id, idp_subject="x", display_name="X"),
        TOrganization(tenant_id=b.tenant_id, name="x"),
        TApAuditLog(tenant_id=b.tenant_id, action="test.x"),
    ]
    for row in rows:
        with ap_db.session(a) as session:
            session.add(row)
            with pytest.raises(DBAPIError):
                session.commit()
    check.equal([count(ap_db.runtime, table, b.tenant_id) for table in ("t_user", "t_organization", "t_ap_audit_log")], [1, 1, 1])


def test_update_and_delete_of_other_tenant_rows_affect_nothing(ap_db, seeded):
    """他テナントの行は UPDATE / DELETE の対象にならない(0 行。エラーにもならない)。"""
    a, b = seeded
    with ap_db.runtime.begin() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        updated = connection.execute(text("UPDATE t_user SET display_name = 'hacked' WHERE tenant_id = :t"), {"t": b.tenant_id}).rowcount
        deleted = connection.execute(text("DELETE FROM t_organization_member WHERE tenant_id = :t"), {"t": b.tenant_id}).rowcount
    check.equal((updated, deleted), (0, 0))
    check.equal([u["display_name"] for u in ap_db.users(b)], ["Test User"])
    check.equal(count(ap_db.runtime, "t_organization_member", b.tenant_id), 1)


def test_changing_tenant_id_of_own_row_is_rejected(ap_db, seeded):
    """自分の行の tenant_id を他テナントに書き換える UPDATE は拒否される(WITH CHECK)。"""
    a, b = seeded
    with ap_db.runtime.begin() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE t_organization SET tenant_id = :b WHERE tenant_id = :a"), {"a": a.tenant_id, "b": b.tenant_id})
    check.equal(count(ap_db.runtime, "t_organization", a.tenant_id), 1)


def test_audit_log_is_append_only_for_runtime(ap_db, seeded):
    """app_runtime は監査ログを UPDATE / DELETE できない(権限が無い)。追記(INSERT)と参照はできる。"""
    a, _ = seeded
    for statement in ("UPDATE t_ap_audit_log SET action = 'tampered'", "DELETE FROM t_ap_audit_log"):
        with ap_db.runtime.connect() as connection:
            apply_tenant_guc(connection, a.tenant_id)
            with pytest.raises(ProgrammingError):
                connection.execute(text(statement))
            connection.rollback()
    check.equal([row["action"] for row in ap_db.audits(a)], ["test.seed"])


def test_cp_agent_cannot_write(ap_db, seeded):
    """app_cp_agent は SELECT / DELETE のみ。INSERT / UPDATE はできない(CP から AP へ書き込まない。05 #31)。"""
    a, _ = seeded
    statements = [
        "INSERT INTO t_organization (tenant_id, name) VALUES (:t, 'by-agent')",
        "UPDATE t_user SET display_name = 'by-agent' WHERE tenant_id = :t",
    ]
    for statement in statements:
        with ap_db.agent.connect() as connection:
            apply_tenant_guc(connection, a.tenant_id)
            with pytest.raises(ProgrammingError):
                connection.execute(text(statement), {"t": a.tenant_id})
            connection.rollback()
    check.equal([o["name"] for o in ap_db.orgs(a)], [f"org-{a.tenant_code}"])


def test_created_by_cannot_point_to_other_tenant_user(ap_db, seeded):
    """created_by に他テナントのユーザーを指定した行は、複合外部キー (tenant_id, created_by) で拒否される。"""
    a, b = seeded
    foreign = ap_db.users(b)[0]["id"]
    with ap_db.session(a) as session:
        session.add(TOrganization(tenant_id=a.tenant_id, name="x", created_by=foreign))
        with pytest.raises(IntegrityError):
            session.commit()
    with ap_db.session(a) as session:
        session.add(TUser(tenant_id=a.tenant_id, idp_subject="y", display_name="Y", updated_by=foreign))
        with pytest.raises(IntegrityError):
            session.commit()
    check.equal(count(ap_db.runtime, "t_organization", a.tenant_id), 1)


def test_unique_constraints_are_per_tenant(ap_db, seeded):
    """同じ sub・メール・組織名は別テナントなら作れ、同じテナント内では一意制約で拒否される(メールは大文字小文字を区別しない)。"""
    a, b = seeded
    ap_db.add_user(a, sub="same-sub", email="same@example.com")
    ap_db.add_user(b, sub="same-sub", email="same@example.com")
    with ap_db.session(a) as session:
        session.add(TUser(tenant_id=a.tenant_id, idp_subject="other-sub", email="SAME@example.com", display_name="dup"))
        with pytest.raises(IntegrityError):
            session.commit()
    with ap_db.session(a) as session:
        session.add(TUser(tenant_id=a.tenant_id, idp_subject="same-sub", email="third@example.com", display_name="dup"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_no_leftover_connection_state(ap_db, seeded):
    """RLS の GUC がプールに残らない: 続けて別テナント → 未設定で参照しても、前のテナントの行が見えない。"""
    a, b = seeded
    with ap_db.runtime.connect() as connection:
        apply_tenant_guc(connection, a.tenant_id)
        check.equal(connection.execute(text("SELECT count(*) FROM t_user")).scalar_one(), 1)
        connection.rollback()
    with ap_db.runtime.connect() as connection:
        check.equal(connection.execute(text("SELECT count(*) FROM t_user")).scalar_one(), 0)
    with Session(ap_db.runtime) as session:
        check.equal(session.connection().execute(text("SELECT count(*) FROM t_user")).scalar_one(), 0)
