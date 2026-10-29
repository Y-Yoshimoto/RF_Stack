# -*- coding: utf-8 -*-
"""ToDo の編集権限(ToDoApp.md §3、§9.3、§10 #7 / #8)のテスト。

- 項目(タイトル・説明・期限・優先度)の変更 / 削除 / 閲覧範囲・公開先組織の変更: ``tenant_admin`` と作成者
- ステータスの変更 / 担当者の変更: 上に加えて担当者
- 権限は**実際に値が変わる項目**だけで判定する(同じ値は変更とみなさない)
- 判定の順序: 入力の形式(422)→ 閲覧範囲(404)→ 版(412)→ 権限(403)→ 現在の状態に依存する検証(422)
"""
import datetime as dt
import uuid

import pytest
import pytest_check as check

from main_app.services.common import UNSET
from main_app.services.errors import (
    InvalidTodoAssigneesError,
    InvalidTodoOrganizationsError,
    TodoNotFoundError,
    TodoPermissionDeniedError,
    TodoValidationError,
    TodoVersionConflictError,
)

# 操作: (名前, 呼び出し, 許可される人)。tenant_admin / 作成者 / 担当者 / 閲覧のみの人(other)
ALL_OWNERS = {"admin", "creator"}
OWNERS_AND_ASSIGNEE = {"admin", "creator", "assignee"}


@pytest.fixture
def todo(world):
    """tenant 公開(全員が閲覧可)の ToDo。作成者は creator、担当者は assignee。タイトルなどは固定。"""
    return world.factory.add(
        world.ctx, world.creator, title="original", description="desc", priority="medium", status="open", due_date=None, visibility="tenant", assignees=[world.assignee]
    )


def attempt(world, actor_key, todo_id, call):
    """``call(service, todo_id)`` を実行し、結果を 'ok' / 例外の operation / 例外名 で返す。"""
    try:
        world.call(world.people[actor_key], lambda s: call(s, todo_id))
    except TodoPermissionDeniedError as exc:
        return f"403:{exc.operation}"
    except Exception as exc:
        return type(exc).__name__
    return "ok"


OPERATIONS = {
    "edit_title": (lambda s, i: s.update_todo(i, expected_version=1, title="changed"), "edit_fields", ALL_OWNERS),
    "edit_description": (lambda s, i: s.update_todo(i, expected_version=1, description="new description"), "edit_fields", ALL_OWNERS),
    "edit_due_date": (lambda s, i: s.update_todo(i, expected_version=1, due_date=dt.date(2030, 1, 2)), "edit_fields", ALL_OWNERS),
    "edit_priority": (lambda s, i: s.update_todo(i, expected_version=1, priority="high"), "edit_fields", ALL_OWNERS),
    "change_status": (lambda s, i: s.update_todo(i, expected_version=1, status="done"), "change_status", OWNERS_AND_ASSIGNEE),
    "change_visibility": (lambda s, i: s.update_todo(i, expected_version=1, visibility="private"), "change_visibility", ALL_OWNERS),
    "delete": (lambda s, i: s.delete_todo(i, expected_version=1), "delete", ALL_OWNERS),
    "change_assignees": (lambda s, i: s.set_assignees(i, expected_version=1, user_ids=[]), "change_assignees", OWNERS_AND_ASSIGNEE),
}


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
@pytest.mark.parametrize("actor_key", ["admin", "creator", "assignee", "m1"])
def test_permission_matrix(world, todo, operation, actor_key):
    """操作ごとの権限は表のとおり: 許可される人は成功し、それ以外の閲覧者は 403(todo_operation_forbidden。operation に拒否した操作)。"""
    call, name, allowed = OPERATIONS[operation]
    expected = "ok" if actor_key in allowed else f"403:{name}"
    check.equal(attempt(world, actor_key, todo, call), expected)


class TestPermissionDeniedLeavesNoTrace:
    """403 のときは何も変えない。"""

    def test_denied_update_changes_nothing(self, world, todo):
        """権限の無い更新は、値・版・アクティビティ・監査ログのどれも変えない。"""
        before = (world.todo(todo)["version"], world.todo(todo)["title"], len(world.activities(todo)), len(world.todo_audits(todo)))
        with pytest.raises(TodoPermissionDeniedError) as caught:
            world.call(world.assignee, lambda s: s.update_todo(todo, expected_version=1, title="hijack", status="done"))
        check.equal(caught.value.operation, "edit_fields")
        check.equal(caught.value.code, "todo_operation_forbidden")
        after = (world.todo(todo)["version"], world.todo(todo)["title"], len(world.activities(todo)), len(world.todo_audits(todo)))
        check.equal(after, before)
        check.equal(world.todo(todo)["status"], "open", "同じ更新の中の許可される項目(status)も適用されない")

    def test_denied_delete_keeps_the_todo(self, world, todo):
        """権限の無い削除では論理削除されない。"""
        with pytest.raises(TodoPermissionDeniedError):
            world.call(world.m1, lambda s: s.delete_todo(todo, expected_version=1))
        check.is_none(world.todo(todo)["deleted_at"])


class TestOnlyChangedFieldsAreChecked:
    """権限は実際に値が変わる項目で判定する(§10 #7)。"""

    def test_assignee_sending_all_fields_with_only_status_changed(self, world, todo):
        """担当者が編集画面のように全項目を送っても、値が変わるのがステータスだけなら通る。変わらない項目は変更とみなさない。"""
        view = world.call(
            world.assignee,
            lambda s: s.update_todo(
                todo, expected_version=1, title="original", description="desc", due_date=None, priority="medium", status="in_progress", visibility="tenant", organization_ids=[]
            ),
        )
        check.equal((view.status.value, view.version), ("in_progress", 2))
        check.equal([a["action"] for a in world.activities(todo)], ["status_changed"])

    def test_assignee_changing_any_field_is_denied_even_if_status_also_sent(self, world, todo):
        """担当者が値の変わる項目(優先度)を送れば、ステータスと一緒でも 403(edit_fields)。"""
        with pytest.raises(TodoPermissionDeniedError) as caught:
            world.call(world.assignee, lambda s: s.update_todo(todo, expected_version=1, priority="high", status="done"))
        check.equal(caught.value.operation, "edit_fields")

    def test_same_values_are_not_a_change_for_anyone(self, world, todo):
        """同じ値だけを送った更新は、権限が無い人でも通り(何も変わらない)、版を変えず、アクティビティも監査ログも残さない。"""
        before_audits = len(world.todo_audits(todo))
        view = world.call(world.m1, lambda s: s.update_todo(todo, expected_version=1, title="original", description="desc", priority="medium", status="open", visibility="tenant"))
        check.equal(view.version, 1)
        check.equal(len(world.todo_audits(todo)), before_audits)
        check.equal(world.activities(todo), [])
        check.equal(world.todo(todo)["version"], 1)

    def test_empty_patch_is_a_noop(self, world, todo):
        """何も送らない更新も何も変えない。版が古ければ 412 にはなる。"""
        check.equal(world.call(world.assignee, lambda s: s.update_todo(todo, expected_version=1)).version, 1)
        with pytest.raises(TodoVersionConflictError):
            world.call(world.assignee, lambda s: s.update_todo(todo, expected_version=2))

    def test_title_whitespace_only_difference_is_no_change(self, world, todo):
        """前後の空白を除くと同じタイトルは、変更とみなさない(担当者でも通る)。"""
        view = world.call(world.assignee, lambda s: s.update_todo(todo, expected_version=1, title="  original  ", status="done"))
        check.equal((view.title, view.status.value, view.version), ("original", "done", 2))

    def test_clearing_an_already_empty_description_is_no_change(self, world):
        """説明が空の ToDo に None / 空文字を送っても変更とみなさない(担当者でも通る)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.assignee], description=None)
        for value in (None, ""):
            view = world.call(world.assignee, lambda s, value=value: s.update_todo(todo_id, expected_version=1, description=value))
            check.equal(view.version, 1)

    def test_organization_ids_unchanged_is_no_visibility_change(self, world):
        """公開先を同じ集合(順序違いを含む)で送るのは変更ではない。担当者でも通る。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1, world.o2], assignees=[world.assignee])
        view = world.call(world.assignee, lambda s: s.update_todo(todo_id, expected_version=1, visibility="organization", organization_ids=[world.o2, world.o1], status="done"))
        check.equal((view.status.value, view.version), ("done", 2))
        check.equal(sorted(world.org_rows(todo_id)), sorted([world.o1, world.o2]))

    def test_changing_organizations_requires_visibility_permission(self, world):
        """公開先組織だけを変えるのも閲覧範囲の変更(change_visibility)。担当者は 403。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1], assignees=[world.assignee])
        with pytest.raises(TodoPermissionDeniedError) as caught:
            world.call(world.assignee, lambda s: s.update_todo(todo_id, expected_version=1, organization_ids=[world.o1, world.o2]))
        check.equal(caught.value.operation, "change_visibility")

    def test_admin_who_is_not_creator_can_edit_everything(self, world, todo):
        """tenant_admin は作成者でなくても、項目・ステータス・閲覧範囲を同時に変更できる。"""
        view = world.call(world.admin, lambda s: s.update_todo(todo, expected_version=1, title="by admin", status="done", visibility="private"))
        check.equal((view.title, view.status.value, view.visibility.value, view.updated_by), ("by admin", "done", "private", world.admin.id))

    def test_member_who_is_not_creator_or_assignee_cannot_do_anything(self, world, todo):
        """作成者でも担当者でもない member(tenant 公開で閲覧のみ)は、ステータスも担当者も変更できない。"""
        check.equal(attempt(world, "m1", todo, lambda s, i: s.update_todo(i, expected_version=1, status="done")), "403:change_status")
        check.equal(attempt(world, "m1", todo, lambda s, i: s.set_assignees(i, expected_version=1, user_ids=[world.m1.id])), "403:change_assignees")

    def test_creator_loses_nothing_when_not_admin(self, world):
        """member の作成者は、自分の ToDo の項目・削除・閲覧範囲を変更できる(tenant_admin でなくても)。"""
        todo_id = world.factory.add(world.ctx, world.m1, visibility="private")
        view = world.call(world.m1, lambda s: s.update_todo(todo_id, expected_version=1, title="mine", visibility="tenant"))
        check.equal((view.title, view.visibility.value), ("mine", "tenant"))
        world.call(world.m1, lambda s: s.delete_todo(todo_id, expected_version=2))
        check.is_not_none(world.todo(todo_id)["deleted_at"])


class TestEvaluationOrder:
    """判定の順序: 形式 422 → 404 → 412 → 403 → 状態依存の 422(§10 #8)。"""

    def test_format_error_comes_before_not_found(self, world):
        """存在しない(または見えない)ToDo でも、入力の形式が不正なら先に TodoValidationError(422)。"""
        hidden = world.factory.add(world.ctx, world.creator, visibility="private")
        for todo_id in (uuid.uuid4(), hidden):
            with pytest.raises(TodoValidationError) as caught:
                world.call(world.outsider, lambda s, todo_id=todo_id: s.update_todo(todo_id, expected_version=1, title="  "))
            check.equal((caught.value.field, caught.value.reason), ("title", "required"))
            with pytest.raises(TodoValidationError):
                world.call(world.outsider, lambda s, todo_id=todo_id: s.set_assignees(todo_id, expected_version=1, user_ids=["x"]))

    def test_not_found_comes_before_version_conflict(self, world):
        """見えない ToDo は、版が違っても 412 ではなく 404(版の情報で存在を推測させない)。"""
        hidden = world.factory.add(world.ctx, world.creator, visibility="private")
        with pytest.raises(TodoNotFoundError):
            world.call(world.outsider, lambda s: s.update_todo(hidden, expected_version=99, title="x"))

    def test_version_conflict_comes_before_permission(self, world, todo):
        """権限の無い人でも、版が違えば 403 ではなく 412(TodoVersionConflictError。期待値と現在値付き)。"""
        with pytest.raises(TodoVersionConflictError) as caught:
            world.call(world.m1, lambda s: s.update_todo(todo, expected_version=5, title="x"))
        check.equal((caught.value.expected_version, caught.value.actual_version, caught.value.code), (5, 1, "todo_version_conflict"))
        with pytest.raises(TodoVersionConflictError):
            world.call(world.m1, lambda s: s.delete_todo(todo, expected_version=5))
        with pytest.raises(TodoVersionConflictError):
            world.call(world.m1, lambda s: s.set_assignees(todo, expected_version=5, user_ids=[]))

    def test_permission_comes_before_state_dependent_validation(self, world, todo):
        """権限の無い人が存在しない組織・ユーザーを指定しても、先に 403。権限のある人なら 422(InvalidTodoOrganizationsError / InvalidTodoAssigneesError)。"""
        ghost = uuid.uuid4()
        with pytest.raises(TodoPermissionDeniedError):
            world.call(world.assignee, lambda s: s.update_todo(todo, expected_version=1, visibility="organization", organization_ids=[ghost]))
        with pytest.raises(InvalidTodoOrganizationsError):
            world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, visibility="organization", organization_ids=[ghost]))
        with pytest.raises(TodoPermissionDeniedError):
            world.call(world.m1, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[ghost]))
        with pytest.raises(InvalidTodoAssigneesError):
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[ghost]))

    def test_version_conflict_comes_before_state_dependent_validation(self, world, todo):
        """版が違えば、存在しない組織・ユーザーの指定より先に 412。"""
        with pytest.raises(TodoVersionConflictError):
            world.call(world.creator, lambda s: s.update_todo(todo, expected_version=3, visibility="organization", organization_ids=[uuid.uuid4()]))
        with pytest.raises(TodoVersionConflictError):
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=3, user_ids=[uuid.uuid4()]))

    def test_unset_is_not_confused_with_none(self, world, todo):
        """UNSET(未指定)は変更なし、None(description / due_date)は消す、それ以外の None は 422 required。"""
        check.equal(world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, description=UNSET, due_date=UNSET)).description, "desc")
        check.is_none(world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, description=None)).description)
        for field in ("title", "priority", "status", "visibility"):
            with pytest.raises(TodoValidationError) as caught:
                world.call(world.creator, lambda s, field=field: s.update_todo(todo, expected_version=2, **{field: None}))
            check.equal((caught.value.field, caught.value.reason), (field, "required"))
