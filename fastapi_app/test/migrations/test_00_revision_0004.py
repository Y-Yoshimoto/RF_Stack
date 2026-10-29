# -*- coding: utf-8 -*-
"""Alembic リビジョン 0004(``add_todo_comments_and_checklist``)の upgrade → downgrade → upgrade のテスト。

使い捨てのスキーマの中で 0001 から順に適用して確認する(``conftest.py``。開発 DB のテーブルには触れず、終了時にロールバックする)。
確認すること: 新しいテーブル・列・制約・インデックス・RLS ができる / 既存の行の ``checklist_version`` が 1 / アクティビティの CHECK に
``checklist_changed`` が加わる / downgrade が ``checklist_changed`` の行を消して元に戻る(他の行は残る)/ downgrade 後に再度 upgrade できる /
モデル(``app_plane_metadata``)との差分が無い。
"""
import uuid

import pytest
import pytest_check as check
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from main_app.models import app_plane_metadata

NEW_TABLES = ("t_todo_comment", "t_todo_checklist_item")
BASE = ("0001", "0002", "0003")


def seed_at_0003(scratch):
    """0003 までの状態に、ユーザー・ToDo・アクティビティ(既存の種別)を作る。"""
    tenant_id, user_id, todo_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scratch.as_tenant(tenant_id)
    c = scratch.connection
    c.execute(text("INSERT INTO t_user (tenant_id, id, idp_subject, display_name) VALUES (:t, :u, 'sub', 'U')"), {"t": tenant_id, "u": user_id})
    c.execute(text("INSERT INTO t_todo (tenant_id, id, created_by, updated_by, title) VALUES (:t, :d, :u, :u, 'existing')"), {"t": tenant_id, "d": todo_id, "u": user_id})
    c.execute(
        text("INSERT INTO t_todo_activity (tenant_id, todo_id, actor_id, action, payload) VALUES (:t, :d, :u, 'created', '{}'::jsonb)"),
        {"t": tenant_id, "d": todo_id, "u": user_id},
    )
    return tenant_id, user_id, todo_id


def add_new_rows(scratch, tenant_id, user_id, todo_id):
    """0004 の状態で、コメント・項目・checklist_changed のアクティビティを作る。"""
    c = scratch.connection
    c.execute(text("INSERT INTO t_todo_comment (tenant_id, todo_id, author_id, body) VALUES (:t, :d, :u, 'hello')"), {"t": tenant_id, "d": todo_id, "u": user_id})
    c.execute(text("INSERT INTO t_todo_checklist_item (tenant_id, todo_id, title, position, created_by, updated_by) VALUES (:t, :d, 'i0', 0, :u, :u)"), {"t": tenant_id, "d": todo_id, "u": user_id})
    c.execute(text("UPDATE t_todo SET checklist_version = 5 WHERE id = :d"), {"d": todo_id})
    for payload in ('{"op": "added"}', '{"op": "checked"}'):
        c.execute(
            text("INSERT INTO t_todo_activity (tenant_id, todo_id, actor_id, action, payload) VALUES (:t, :d, :u, 'checklist_changed', CAST(:p AS jsonb))"),
            {"t": tenant_id, "d": todo_id, "u": user_id, "p": payload},
        )


class TestUpgrade:
    """0003 → 0004。"""

    def test_creates_tables_columns_and_default_version(self, scratch):
        """新しい 2 テーブルと t_todo.checklist_version ができる。既存の ToDo の checklist_version は 1(NOT NULL、既定 1)。"""
        scratch.upgrade(*BASE)
        seed = seed_at_0003(scratch)
        check.is_false(any(scratch.exists(t) for t in NEW_TABLES))
        check.is_not_in("checklist_version", scratch.columns("t_todo"))
        scratch.upgrade("0004")
        check.is_true(all(scratch.exists(t) for t in NEW_TABLES))
        check.equal(scratch.columns("t_todo_comment"), {"tenant_id", "id", "todo_id", "author_id", "body", "version", "edited_at", "created_at", "updated_at", "deleted_at"})
        check.equal(
            scratch.columns("t_todo_checklist_item"),
            {"tenant_id", "id", "todo_id", "title", "position", "is_done", "done_at", "done_by", "created_by", "updated_by", "version", "created_at", "updated_at"},
        )
        scratch.as_tenant(seed[0])
        check.equal(scratch.query("SELECT checklist_version FROM t_todo"), [{"checklist_version": 1}])
        column = scratch.query("SELECT is_nullable, column_default FROM information_schema.columns WHERE table_schema = :s AND table_name = 't_todo' AND column_name = 'checklist_version'", s=scratch.schema)[0]
        check.equal((column["is_nullable"], column["column_default"]), ("NO", "1"))

    def test_rls_is_enabled_and_forced_on_new_tables(self, scratch):
        """新しい 2 テーブルは ENABLE / FORCE の RLS とポリシー tenant_isolation を持つ(使い捨てのスキーマ内)。GUC 無しは 0 件。"""
        scratch.upgrade(*BASE, "0004")
        tenant_id, user_id, todo_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        for table in NEW_TABLES:
            flags = scratch.query("SELECT relrowsecurity AS enabled, relforcerowsecurity AS forced FROM pg_class WHERE relname = :t AND relnamespace = CAST(:s AS regnamespace)", t=table, s=scratch.schema)
            check.equal(flags, [{"enabled": True, "forced": True}], table)
            policies = scratch.query("SELECT policyname FROM pg_policies WHERE schemaname = :s AND tablename = :t", s=scratch.schema, t=table)
            check.equal(policies, [{"policyname": "tenant_isolation"}], table)
        scratch.as_tenant(tenant_id)
        c = scratch.connection
        c.execute(text("INSERT INTO t_user (tenant_id, id, idp_subject, display_name) VALUES (:t, :u, 's', 'U')"), {"t": tenant_id, "u": user_id})
        c.execute(text("INSERT INTO t_todo (tenant_id, id, created_by, updated_by, title) VALUES (:t, :d, :u, :u, 'x')"), {"t": tenant_id, "d": todo_id, "u": user_id})
        c.execute(text("INSERT INTO t_todo_comment (tenant_id, todo_id, author_id, body) VALUES (:t, :d, :u, 'x')"), {"t": tenant_id, "d": todo_id, "u": user_id})
        check.equal(scratch.scalar("SELECT count(*) FROM t_todo_comment"), 1)
        scratch.as_tenant(uuid.uuid4())
        check.equal(scratch.scalar("SELECT count(*) FROM t_todo_comment"), 0, "別のテナントの GUC では所有者でも見えない")
        c.execute(text("SELECT set_config('app.current_tenant', '', true)"))
        check.equal(scratch.scalar("SELECT count(*) FROM t_todo_comment"), 0, "GUC が空なら 0 件")

    def test_constraints_and_indexes(self, scratch):
        """制約とインデックス: 位置の一意制約は DEFERRABLE INITIALLY DEFERRED、コメントの一覧用部分インデックス(deleted_at IS NULL)、複合外部キー、完了の整合性の CHECK。"""
        scratch.upgrade(*BASE, "0004")
        unique = scratch.query(
            "SELECT condeferrable, condeferred FROM pg_constraint WHERE conrelid = CAST(:r AS regclass) AND contype = 'u' AND conname LIKE '%position%'", r=f"{scratch.schema}.t_todo_checklist_item"
        )
        check.equal(unique, [{"condeferrable": True, "condeferred": True}])
        index = scratch.query("SELECT indexdef FROM pg_indexes WHERE schemaname = :s AND indexname = 'ix_t_todo_comment_tenant_id_todo_id_created_at_id'", s=scratch.schema)
        check.equal(len(index), 1)
        check.is_true("(tenant_id, todo_id, created_at, id)" in index[0]["indexdef"] and "deleted_at IS NULL" in index[0]["indexdef"], index)
        checks = {r["conname"] for r in scratch.query("SELECT conname FROM pg_constraint WHERE contype = 'c' AND connamespace = CAST(:s AS regnamespace)", s=scratch.schema)}
        names = (
            "t_todo_comment_body_length_check",
            "t_todo_checklist_item_done_consistent_check",
            "t_todo_checklist_item_title_length_check",
            "t_todo_checklist_item_position_non_negative_check",
            "t_todo_checklist_version_positive_check",
        )
        for name in names:
            check.is_in(name, checks)
        fks = scratch.query(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE contype = 'f' AND conrelid IN (CAST(:a AS regclass), CAST(:b AS regclass))",
            a=f"{scratch.schema}.t_todo_comment",
            b=f"{scratch.schema}.t_todo_checklist_item",
        )
        check.equal(len(fks), 6, "コメント 2(todo / author)+ 項目 4(todo / created_by / updated_by / done_by)")
        check.is_true(all("(tenant_id," in fk["definition"] for fk in fks), fks)

    def test_activity_action_check_accepts_checklist_changed_only_after_upgrade(self, scratch):
        """アクティビティの種別の CHECK: 0004 の前は checklist_changed を拒否、後は受け付ける。"""
        scratch.upgrade(*BASE)
        tenant_id, user_id, todo_id = seed_at_0003(scratch)
        insert = text("INSERT INTO t_todo_activity (tenant_id, todo_id, actor_id, action, payload) VALUES (:t, :d, :u, 'checklist_changed', '{}'::jsonb)")
        params = {"t": tenant_id, "d": todo_id, "u": user_id}
        with pytest.raises(IntegrityError):
            with scratch.connection.begin_nested():
                scratch.connection.execute(insert, params)
        scratch.upgrade("0004")
        scratch.connection.execute(insert, params)
        check.equal(scratch.scalar("SELECT count(*) FROM t_todo_activity WHERE action = 'checklist_changed'"), 1)

    def test_schema_matches_the_models(self, scratch):
        """マイグレーションで作ったスキーマとモデル(app_plane_metadata)の差分が無い(autogenerate が検出できる範囲。テーブル・列・型・制約・インデックス)。"""
        scratch.upgrade(*BASE, "0004")
        context = MigrationContext.configure(scratch.connection, opts={"compare_type": True})
        diffs = compare_metadata(context, app_plane_metadata)
        check.equal(diffs, [])


class TestDowngrade:
    """0004 → 0003。"""

    def test_downgrade_removes_new_objects_and_checklist_activities(self, scratch):
        """checklist_changed のアクティビティ行・コメント・項目がある状態でも downgrade できる: 新しいテーブルと列が消え、checklist_changed の行だけが削除され、他の行は残る。"""
        scratch.upgrade(*BASE)
        tenant_id, user_id, todo_id = seed_at_0003(scratch)
        scratch.upgrade("0004")
        add_new_rows(scratch, tenant_id, user_id, todo_id)
        check.equal(scratch.scalar("SELECT count(*) FROM t_todo_activity"), 3)
        scratch.downgrade("0004")
        check.is_false(any(scratch.exists(t) for t in NEW_TABLES))
        check.is_not_in("checklist_version", scratch.columns("t_todo"))
        scratch.as_tenant(tenant_id)
        check.equal([r["action"] for r in scratch.query("SELECT action FROM t_todo_activity")], ["created"])
        check.equal(scratch.scalar("SELECT count(*) FROM t_todo"), 1, "ToDo 本体は残る")

    def test_activity_check_rejects_checklist_changed_after_downgrade(self, scratch):
        """downgrade 後は、アクティビティの種別の CHECK が元に戻り checklist_changed を拒否する。"""
        scratch.upgrade(*BASE)
        tenant_id, user_id, todo_id = seed_at_0003(scratch)
        scratch.upgrade("0004")
        scratch.downgrade("0004")
        with pytest.raises(IntegrityError):
            with scratch.connection.begin_nested():
                scratch.connection.execute(
                    text("INSERT INTO t_todo_activity (tenant_id, todo_id, actor_id, action, payload) VALUES (:t, :d, :u, 'checklist_changed', '{}'::jsonb)"),
                    {"t": tenant_id, "d": todo_id, "u": user_id},
                )

    def test_downgrade_leaves_no_policy_or_orphans(self, scratch):
        """downgrade 後に、新しいテーブルのポリシー・インデックス・制約が残っていない。"""
        scratch.upgrade(*BASE, "0004")
        scratch.downgrade("0004")
        leftovers = scratch.query("SELECT tablename FROM pg_policies WHERE schemaname = :s AND tablename = ANY(:names)", s=scratch.schema, names=list(NEW_TABLES))
        check.equal(leftovers, [])
        indexes = scratch.query("SELECT indexname FROM pg_indexes WHERE schemaname = :s AND (indexname LIKE '%todo_comment%' OR indexname LIKE '%checklist_item%')", s=scratch.schema)
        check.equal(indexes, [])
        constraints = scratch.query("SELECT conname FROM pg_constraint WHERE connamespace = CAST(:s AS regnamespace) AND conname LIKE '%checklist_version%'", s=scratch.schema)
        check.equal(constraints, [])


class TestRoundTrip:
    """upgrade → downgrade → upgrade。"""

    def test_upgrade_downgrade_upgrade(self, scratch):
        """0004 を適用 → 戻す → 再度適用できる。再適用後は新しいテーブルが空で、既存の ToDo の checklist_version は 1(downgrade 前の値は失われる)、スキーマはモデルと一致する。"""
        scratch.upgrade(*BASE)
        tenant_id, user_id, todo_id = seed_at_0003(scratch)
        scratch.upgrade("0004")
        add_new_rows(scratch, tenant_id, user_id, todo_id)
        scratch.downgrade("0004")
        scratch.upgrade("0004")
        scratch.as_tenant(tenant_id)
        check.equal([scratch.scalar(f"SELECT count(*) FROM {t}") for t in NEW_TABLES], [0, 0])
        check.equal(scratch.query("SELECT checklist_version FROM t_todo"), [{"checklist_version": 1}])
        check.equal([r["action"] for r in scratch.query("SELECT action FROM t_todo_activity")], ["created"])
        context = MigrationContext.configure(scratch.connection, opts={"compare_type": True})
        check.equal(compare_metadata(context, app_plane_metadata), [])

    def test_second_cycle_also_works(self, scratch):
        """2 周目の upgrade → downgrade → upgrade も成功する(名前の衝突が起きない)。"""
        scratch.upgrade(*BASE)
        for _ in range(2):
            scratch.upgrade("0004")
            scratch.downgrade("0004")
        scratch.upgrade("0004")
        check.is_true(all(scratch.exists(t) for t in NEW_TABLES))

    def test_public_schema_is_untouched(self, scratch):
        """(安全確認)使い捨てのスキーマ以外に、新しいテーブルを作っていない: 作成したテーブルは全て使い捨てのスキーマにあり、search_path は使い捨てのスキーマだけ。"""
        scratch.upgrade(*BASE, "0004")
        check.equal(scratch.scalar("SELECT current_schema()"), scratch.schema)
        in_scratch = {r["table_name"] for r in scratch.query("SELECT table_name FROM information_schema.tables WHERE table_schema = :s", s=scratch.schema)}
        check.is_true({"t_user", "t_todo", *NEW_TABLES} <= in_scratch)
