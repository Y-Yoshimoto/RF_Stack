# -*- coding: utf-8 -*-
"""操作の権限の表(``todo_permissions`` / ``comment_permissions``)を、仕様(ToDoApp.md §3・§9.3)の表と照合するテスト。

DB を使わない。期待値は実装から導かず、仕様の表をそのまま書き下した(オラクル)。
役割: ``admin``(tenant_admin)/ ``creator``(作成者)/ ``assignee``(担当者)/ ``viewer``(閲覧できるだけの member)/ ``admin_creator``(作成者でもある管理者)。
"""
import uuid

import pytest
import pytest_check as check

from main_app.services.todo_policy import TodoActor, TodoOperation, comment_permissions, todo_permissions

TENANT_ID = uuid.uuid4()
CREATOR_ID, ASSIGNEE_ID, VIEWER_ID, ADMIN_ID = (uuid.uuid4() for _ in range(4))

ACTORS = {
    "admin": TodoActor(tenant_id=TENANT_ID, user_id=ADMIN_ID, roles=frozenset({"tenant_admin"})),
    "creator": TodoActor(tenant_id=TENANT_ID, user_id=CREATOR_ID, roles=frozenset({"member"})),
    "assignee": TodoActor(tenant_id=TENANT_ID, user_id=ASSIGNEE_ID, roles=frozenset({"member"})),
    "viewer": TodoActor(tenant_id=TENANT_ID, user_id=VIEWER_ID, roles=frozenset({"member"})),
    # 作成者が tenant_admin のロールを持つ場合
    "admin_creator": TodoActor(tenant_id=TENANT_ID, user_id=CREATOR_ID, roles=frozenset({"tenant_admin", "member"})),
}

# 仕様 §9.3「操作の権限」の表: 操作 -> (admin, creator, assignee, viewer)
TODO_TABLE = {
    "can_edit_fields": (True, True, False, False),
    "can_change_status": (True, True, True, False),
    "can_change_visibility": (True, True, False, False),
    "can_change_assignees": (True, True, True, False),
    "can_delete": (True, True, False, False),
    "can_comment": (True, True, True, True),
    "can_edit_checklist": (True, True, False, False),
    "can_check_checklist": (True, True, True, False),
}
ROLE_COLUMNS = ("admin", "creator", "assignee", "viewer")


def permissions_of(role: str):
    """``role`` の操作者が、作成者 = CREATOR・担当者 = ASSIGNEE の ToDo に対して持つ権限。"""
    return todo_permissions(ACTORS[role], created_by=CREATOR_ID, assignee_ids=[ASSIGNEE_ID])


@pytest.mark.parametrize("flag", sorted(TODO_TABLE))
def test_todo_permission_table_matches_the_spec(flag):
    """``todo_permissions`` の各権限が、仕様の表(admin / 作成者 / 担当者 / 閲覧だけの人)と一致する。"""
    actual = tuple(getattr(permissions_of(role), flag) for role in ROLE_COLUMNS)
    check.equal(actual, TODO_TABLE[flag], flag)


def test_todo_permission_fields_are_exactly_the_documented_ones():
    """権限のフィールド集合が表と同じ(表に無い権限が黙って増えていない)。"""
    check.equal(set(permissions_of("admin").__slots__), set(TODO_TABLE))


def test_admin_who_is_also_creator_is_not_restricted():
    """作成者であり tenant_admin でもある人は、どの権限も持つ。"""
    permissions = todo_permissions(ACTORS["admin_creator"], created_by=CREATOR_ID, assignee_ids=[])
    check.is_true(all(getattr(permissions, flag) for flag in TODO_TABLE))


def test_assignee_who_is_also_creator_keeps_creator_rights():
    """作成者が自分を担当者にもしている場合も、作成者の権限(項目の編集・チェックリストの編集)を持つ。"""
    permissions = todo_permissions(ACTORS["creator"], created_by=CREATOR_ID, assignee_ids=[CREATOR_ID, ASSIGNEE_ID])
    check.is_true(permissions.can_edit_fields and permissions.can_edit_checklist)


def test_viewer_only_has_comment_right():
    """閲覧できるだけの member(作成者でも担当者でもない)が持つのはコメントの権利だけ。担当者の一覧に含まれなければ担当者ではない。"""
    permissions = todo_permissions(ACTORS["viewer"], created_by=CREATOR_ID, assignee_ids=[ASSIGNEE_ID])
    check.equal([flag for flag in TODO_TABLE if getattr(permissions, flag)], ["can_comment"])


def test_assignee_with_no_assignees_list_is_not_assignee():
    """担当者の一覧が空なら、担当者の権限は誰にも付かない(担当者 = 一覧に含まれること)。"""
    permissions = todo_permissions(ACTORS["assignee"], created_by=CREATOR_ID, assignee_ids=[])
    check.equal([flag for flag in TODO_TABLE if getattr(permissions, flag)], ["can_comment"])


def test_checklist_view_follows_the_flags():
    """画面向けの ``checklist``(can_edit / can_check)は ``can_edit_checklist`` / ``can_check_checklist`` と同じ値。"""
    for role in ROLE_COLUMNS:
        permissions = permissions_of(role)
        check.equal((permissions.checklist.can_edit, permissions.checklist.can_check), (permissions.can_edit_checklist, permissions.can_check_checklist), role)


# 仕様 §9.3「コメントごとの権限」: (操作者, コメントの投稿者) -> (can_edit, can_delete)
@pytest.mark.parametrize(
    ("role", "author_is_actor", "expected"),
    [
        ("creator", True, (True, True)),  # 投稿者は編集・削除できる
        ("assignee", True, (True, True)),
        ("viewer", True, (True, True)),
        ("admin", True, (True, True)),  # tenant_admin も自分のコメントは編集・削除できる
        ("admin", False, (False, True)),  # tenant_admin は他人のコメントを削除できるが編集できない
        ("creator", False, (False, False)),  # ToDo の作成者でも他人のコメントは編集も削除もできない
        ("assignee", False, (False, False)),
        ("viewer", False, (False, False)),
    ],
)
def test_comment_permission_table_matches_the_spec(role, author_is_actor, expected):
    """``comment_permissions`` が仕様の表(投稿者 / tenant_admin(投稿者以外)/ それ以外)と一致する。"""
    actor = ACTORS[role]
    author_id = actor.user_id if author_is_actor else uuid.uuid4()
    permissions = comment_permissions(actor, author_id=author_id)
    check.equal((permissions.can_edit, permissions.can_delete), expected)


def test_comment_permissions_do_not_depend_on_the_todo_roles():
    """コメントごとの権限は ToDo の作成者・担当者かどうかに依存しない(コメントの投稿者と tenant_admin だけで決まる)。"""
    author = uuid.uuid4()
    results = {role: comment_permissions(ACTORS[role], author_id=author) for role in ROLE_COLUMNS}
    check.equal({role: (p.can_edit, p.can_delete) for role, p in results.items()}, {"admin": (False, True), "creator": (False, False), "assignee": (False, False), "viewer": (False, False)})


class TestAllows:
    """``allows(operation)`` の対応付けと、判定の場所の取り違えの拒否。"""

    @pytest.mark.parametrize(
        ("operation", "flag"),
        [
            (TodoOperation.EDIT_FIELDS, "can_edit_fields"),
            (TodoOperation.CHANGE_STATUS, "can_change_status"),
            (TodoOperation.CHANGE_VISIBILITY, "can_change_visibility"),
            (TodoOperation.CHANGE_ASSIGNEES, "can_change_assignees"),
            (TodoOperation.DELETE, "can_delete"),
            (TodoOperation.EDIT_CHECKLIST, "can_edit_checklist"),
            (TodoOperation.CHECK_CHECKLIST_ITEM, "can_check_checklist"),
        ],
    )
    def test_todo_operation_maps_to_its_flag(self, operation, flag):
        """ToDo の操作と権限のフラグの対応(全ロールで一致)。"""
        for role in ROLE_COLUMNS:
            permissions = permissions_of(role)
            check.equal(permissions.allows(operation), getattr(permissions, flag), f"{role} {operation}")

    @pytest.mark.parametrize("operation", [TodoOperation.EDIT_COMMENT, TodoOperation.DELETE_COMMENT])
    def test_comment_operations_are_not_judged_per_todo(self, operation):
        """コメントの操作を ``todo_permissions`` で判定しようとすると ValueError(コメントごとに判定する)。"""
        with pytest.raises(ValueError):
            permissions_of("admin").allows(operation)

    @pytest.mark.parametrize("operation", [op for op in TodoOperation if op not in (TodoOperation.EDIT_COMMENT, TodoOperation.DELETE_COMMENT)])
    def test_todo_operations_are_not_judged_per_comment(self, operation):
        """ToDo の操作を ``comment_permissions`` で判定しようとすると ValueError。"""
        with pytest.raises(ValueError):
            comment_permissions(ACTORS["admin"], author_id=ADMIN_ID).allows(operation)

    def test_comment_operation_mapping(self):
        """``allows`` は edit_comment -> can_edit、delete_comment -> can_delete。"""
        permissions = comment_permissions(ACTORS["admin"], author_id=uuid.uuid4())
        check.equal((permissions.allows(TodoOperation.EDIT_COMMENT), permissions.allows(TodoOperation.DELETE_COMMENT)), (False, True))
