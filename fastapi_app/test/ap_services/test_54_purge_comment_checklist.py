# -*- coding: utf-8 -*-
"""テナントの物理削除(``TENANT_DATA_PURGE_TABLES``。ToDoApp.md §7 #9 / §9.1)に、コメントとチェックリスト項目が含まれることのテスト。

- 登録の順序: コメント → チェックリスト項目 → アクティビティ → 担当者 → 公開先組織 → ToDo → … → ユーザー(子を先に消す)
- 登録の網羅: AP の ``tenant_id`` を持つテーブルがすべて登録されている(新しいテーブルを足して登録を忘れると失敗する)
- 実際の削除: 使い捨てのテナントでコメント・項目を含む全データが消え、他テナントのデータは残る
"""
import pytest
import pytest_check as check

from control_plane_app.repositories.app_tenant_data import TENANT_DATA_PURGE_TABLES, AppTenantDataRepository
from main_app.models import app_plane_metadata

TODO_CHILDREN = ("t_todo_comment", "t_todo_checklist_item", "t_todo_activity", "t_todo_assignee", "t_todo_organization")


def test_purge_order_deletes_children_before_parents():
    """コメント・項目・アクティビティ・担当者・公開先組織は ToDo より先、ToDo は組織・ユーザーより先、ユーザーは最後(外部キーを壊さない順)。"""
    tables = list(TENANT_DATA_PURGE_TABLES)
    index = {name: tables.index(name) for name in tables}
    check.equal(tables[:2], ["t_todo_comment", "t_todo_checklist_item"], "コメント → チェックリスト項目 が先頭")
    for child in TODO_CHILDREN:
        check.less(index[child], index["t_todo"], child)
    check.less(index["t_todo"], index["t_organization"])
    check.less(index["t_todo_organization"], index["t_organization"])
    check.equal(tables[-1], "t_user")
    check.equal(len(set(tables)), len(tables), "重複して登録していない")


def test_every_tenant_scoped_table_is_registered_for_purge():
    """AP のメタデータで tenant_id を持つテーブルがすべて物理削除の対象に登録されている(登録漏れは削除後にデータが残る)。"""
    import main_app.models  # noqa: F401 (全モデルを読み込む)

    scoped = {table.name for table in app_plane_metadata.tables.values() if "tenant_id" in table.columns}
    check.equal(scoped - set(TENANT_DATA_PURGE_TABLES), set(), "登録漏れ")
    check.equal(set(TENANT_DATA_PURGE_TABLES) - scoped, set(), "存在しないテーブルの登録")
    check.is_in("t_todo_comment", scoped)
    check.is_in("t_todo_checklist_item", scoped)


def test_foreign_key_order_is_respected_by_metadata():
    """メタデータの外部キーから、子テーブルが親テーブルより先に登録されていることを機械的に確認する(同一 tenant_id の複合キーも含む)。"""
    order = {name: i for i, name in enumerate(TENANT_DATA_PURGE_TABLES)}
    for table in app_plane_metadata.tables.values():
        if table.name not in order:
            continue
        for fk in table.foreign_key_constraints:
            parent = fk.referred_table.name
            if parent == table.name or parent not in order:
                continue
            check.less(order[table.name], order[parent], f"{table.name} は {parent} を参照するので先に削除する")


@pytest.fixture
def populated(ap_db):
    """テナント A(削除する)と B(残す)に、コメント・項目・アクティビティを含む ToDo を作る。"""
    from main_app.services.todo_checklist_service import TodoChecklistService
    from main_app.services.todo_comment_service import TodoCommentService
    from main_app.services.todo_service import TodoService

    tenants = []
    for _ in range(2):
        ctx = ap_db.tenant()
        admin = ap_db.add_user(ctx, display_name="admin")
        member = ap_db.add_user(ctx, display_name="member")
        org = ap_db.add_org(ctx, "org", members=(member.id,))
        with ap_db.session(ctx) as session:
            todo = TodoService(session, actor_user_id=admin.id, actor_roles=("tenant_admin",)).create_todo(
                title="t", visibility="organization", organization_ids=[org.id], assignee_ids=[member.id]
            )
        with ap_db.session(ctx) as session:
            TodoCommentService(session, actor_user_id=member.id, actor_roles=("member",)).create_comment(todo.id, body="hello")
        with ap_db.session(ctx) as session:
            TodoChecklistService(session, actor_user_id=admin.id, actor_roles=("tenant_admin",)).add_item(todo.id, title="item")
        tenants.append(ctx)
    return tenants


def counts(ap_db, ctx):
    return {table: ap_db.count(ctx.tenant_id, table) for table in TENANT_DATA_PURGE_TABLES}


def test_purge_removes_comments_and_checklist_items_and_only_that_tenant(ap_db, populated):
    """物理削除でコメント・項目を含む全テーブルが 0 件になり(外部キー違反にならない)、削除件数がテーブルごとに返る。他テナントのデータは変わらない。"""
    a, b = populated
    before_b = counts(ap_db, b)
    check.greater(before_b["t_todo_comment"], 0)
    check.greater(before_b["t_todo_checklist_item"], 0)
    repository = AppTenantDataRepository(engine_factory=lambda: ap_db.agent)
    result = repository.purge_tenant_data(a.tenant_id)
    check.equal(list(result), list(TENANT_DATA_PURGE_TABLES), "登録順に実行される")
    check.equal((result["t_todo_comment"], result["t_todo_checklist_item"], result["t_todo_activity"]), (1, 1, 2))
    check.equal(set(counts(ap_db, a).values()), {0})
    check.equal(counts(ap_db, b), before_b)


def test_purge_is_idempotent(ap_db, populated):
    """2 回目の物理削除は何も削除せず(全て 0 件)成功する。"""
    a, _ = populated
    repository = AppTenantDataRepository(engine_factory=lambda: ap_db.agent)
    repository.purge_tenant_data(a.tenant_id)
    second = repository.purge_tenant_data(a.tenant_id)
    check.equal(set(second.values()), {0})
