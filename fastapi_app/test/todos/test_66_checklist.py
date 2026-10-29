# -*- coding: utf-8 -*-
"""ToDo のチェックリスト(AP-CHK-01..08、AP-ACT-05、ToDoApp.md §9.3 / §10 #16〜#18・#20・#23)のサービス層のテスト。実サービス + 実 DB(RLS)。

観点: 権限(作成者・tenant_admin は編集系、担当者はチェックだけ、閲覧だけの人は不可。#18 は実際に変わる項目で判定)、404(閲覧できない・他テナント・別 ToDo の項目)、
判定の順序(422 → 404 todo → 404 item → 412 → 403 → 422(状態依存))、上限 100、検証、並べ替え、削除後の詰め直し、版(項目 / チェックリスト)、
完了の整合性、op ごとのアクティビティ、監査ログ、ToDo 本体の ``version`` / ``updated_at`` を変えないこと。
"""
import datetime as dt
import uuid

import pytest
import pytest_check as check
from sqlalchemy.exc import IntegrityError

from main_app.models import TTodoChecklistItem
from main_app.models.todo import TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH, TODO_CHECKLIST_ITEMS_MAX
from main_app.services.errors import TodoChecklistItemNotFoundError, TodoChecklistVersionConflictError, TodoNotFoundError, TodoPermissionDeniedError, TodoValidationError


@pytest.fixture
def todo(world):
    """tenant 公開の ToDo(作成者 = creator、担当者 = assignee)。outsider は閲覧だけできる。"""
    return world.factory.add(world.ctx, world.creator, title="with checklist", visibility="tenant", assignees=[world.assignee])


def add(world, person, todo_id, title="item", **kwargs):
    return world.checklist_call(person, lambda s: s.add_item(todo_id, title=title, **kwargs))


def add_many(world, person, todo_id, titles):
    view = None
    for title in titles:
        view = add(world, person, todo_id, title)
    return view


def get(world, person, todo_id):
    return world.checklist_call(person, lambda s: s.get_checklist(todo_id))


def update(world, person, todo_id, item, **kwargs):
    version = kwargs.pop("expected_version", item.version)
    return world.checklist_call(person, lambda s: s.update_item(todo_id, item.id, expected_version=version, **kwargs))


def titles(view):
    return [item.title for item in view.items]


def seed_items(world, todo_id, count):
    """項目を 1 トランザクションで ``count`` 件作る(上限の確認用。サービスを通さない)。"""
    with world.ap_db.session(world.ctx) as session:
        session.add_all(
            [TTodoChecklistItem(tenant_id=world.ctx.tenant_id, todo_id=todo_id, title=f"seed {i}", position=i, created_by=world.creator.id, updated_by=world.creator.id) for i in range(count)]
        )
        session.commit()


class TestView:
    """参照(get_checklist)とビューの値。"""

    def test_empty_checklist(self, world, todo):
        """項目が無いチェックリスト: version = 1、項目 0、進捗 0/0。"""
        view = get(world, world.outsider, todo)
        check.equal((view.todo_id, view.version, view.items, view.done_count, view.total_count), (todo, 1, (), 0, 0))

    def test_items_in_position_order_with_progress(self, world, todo):
        """項目は position 順。done_count / total_count は完了数と総数。完了した人の表示名つき。"""
        a = world.factory.item(world.ctx, todo, world.creator, title="a", position=1, done_by=world.assignee)
        world.factory.item(world.ctx, todo, world.creator, title="b", position=0)
        world.factory.item(world.ctx, todo, world.creator, title="c", position=2)
        view = get(world, world.admin, todo)
        check.equal((titles(view), view.done_count, view.total_count), (["b", "a", "c"], 1, 3))
        done = next(i for i in view.items if i.id == a)
        check.equal((done.is_done, done.done_by.id, done.done_by.display_name, done.done_by.is_active), (True, world.assignee.id, world.assignee.name, True))
        check.equal([i.position for i in view.items], [0, 1, 2])

    def test_done_by_inactive_user_is_flagged(self, world, todo):
        """完了した人が無効化されたユーザーでも項目は残り、done_by.is_active が False。"""
        world.factory.item(world.ctx, todo, world.creator, done_by=world.inactive)
        item = get(world, world.admin, todo).items[0]
        check.equal((item.done_by.id, item.done_by.is_active), (world.inactive.id, False))

    @pytest.mark.parametrize(
        ("who", "expected"),
        [("admin", (True, True)), ("creator", (True, True)), ("assignee", (False, True)), ("outsider", (False, False)), ("m1", (False, False))],
    )
    def test_permissions_follow_the_viewer(self, world, todo, who, expected):
        """応答の permissions(can_edit / can_check)は閲覧者ごと: 作成者・管理者 = 両方、担当者 = チェックのみ、閲覧だけ = なし。"""
        view = get(world, world.people[who], todo)
        check.equal((view.permissions.can_edit, view.permissions.can_check), expected)

    def test_checklist_progress_does_not_change_status(self, world, todo):
        """すべての項目を完了しても ToDo のステータスは自動で変わらない(AP-CHK-05)。"""
        view = add_many(world, world.creator, todo, ["a", "b"])
        for item in view.items:
            view = update(world, world.assignee, todo, get(world, world.creator, todo).items[item.position], is_done=True)
        check.equal((view.done_count, view.total_count), (2, 2))
        check.equal(world.todo(todo)["status"], "open")


class TestPermissions:
    """作成者・admin は追加・名前変更・削除・並べ替え、担当者はチェックだけ、閲覧だけの人は何も不可(AP-CHK-03 / 04)。"""

    @pytest.fixture
    def base(self, world, todo):
        view = add_many(world, world.creator, todo, ["one", "two"])
        return todo, view

    @pytest.mark.parametrize("who", ["creator", "admin"])
    def test_creator_and_admin_can_edit(self, world, base, who):
        """作成者と tenant_admin は、追加・名前変更・並べ替え・削除ができる。"""
        todo, view = base
        person = world.people[who]
        view = add(world, person, todo, "three")
        view = update(world, person, todo, view.items[0], title="uno")
        view = world.checklist_call(person, lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=[i.id for i in reversed(view.items)]))
        view = world.checklist_call(person, lambda s: s.delete_item(todo, view.items[0].id, expected_version=view.items[0].version))
        check.equal((titles(view), view.total_count), (["two", "uno"], 2))

    @pytest.mark.parametrize("who", ["assignee", "outsider", "m1"])
    def test_non_owners_cannot_edit(self, world, base, who):
        """担当者・閲覧だけの人は、追加・名前変更・削除・並べ替えとも 403 edit_checklist。チェックリストは変わらない。"""
        todo, view = base
        person = world.people[who]
        item = view.items[0]
        attempts = {
            "add": lambda s: s.add_item(todo, title="new"),
            "rename": lambda s: s.update_item(todo, item.id, expected_version=item.version, title="renamed"),
            "delete": lambda s: s.delete_item(todo, item.id, expected_version=item.version),
            "reorder": lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=[i.id for i in reversed(view.items)]),
        }
        for name, func in attempts.items():
            with pytest.raises(TodoPermissionDeniedError) as raised:
                world.checklist_call(person, func)
            check.equal((raised.value.code, raised.value.operation), ("todo_operation_forbidden", "edit_checklist"), name)
        after = get(world, world.admin, todo)
        check.equal((titles(after), after.version), (["one", "two"], view.version))
        check.equal(len(world.checklist_activities(todo)), 2, "追加の 2 行だけ")

    @pytest.mark.parametrize("who", ["creator", "admin", "assignee"])
    def test_creator_admin_assignee_can_check_and_uncheck(self, world, base, who):
        """作成者・tenant_admin・担当者は完了・未完了を切り替えられる。完了者と日時が記録される。"""
        todo, view = base
        person = world.people[who]
        done = update(world, person, todo, view.items[0], is_done=True)
        item = done.items[0]
        check.equal((item.is_done, item.done_by.id, item.done_at is not None, item.version), (True, person.id, True, 2))
        undone = update(world, person, todo, item, is_done=False)
        check.equal((undone.items[0].is_done, undone.items[0].done_by, undone.items[0].done_at, undone.items[0].version), (False, None, None, 3))

    @pytest.mark.parametrize("who", ["outsider", "m1"])
    def test_view_only_cannot_check(self, world, base, who):
        """閲覧だけの人は完了にも未完了にもできない(403 check_checklist_item)。"""
        todo, view = base
        done = update(world, world.creator, todo, view.items[0], is_done=True)
        for item, flag in ((done.items[1], True), (done.items[0], False)):
            with pytest.raises(TodoPermissionDeniedError) as raised:
                update(world, world.people[who], todo, item, is_done=flag)
            check.equal(raised.value.operation, "check_checklist_item")
        check.equal([i.is_done for i in get(world, world.admin, todo).items], [True, False])

    def test_assignee_check_without_rename_is_allowed(self, world, base):
        """§10 #18: 担当者が名前を変えずに完了だけを切り替えるなら通る(編集画面が名前も送ってくる場合でも、同じ名前は変更とみなさない)。"""
        todo, view = base
        item = view.items[0]
        result = update(world, world.assignee, todo, item, title=item.title, is_done=True)
        check.equal((result.items[0].title, result.items[0].is_done), ("one", True))
        ops = [a["payload"]["op"] for a in world.checklist_activities(todo)]
        check.equal(ops, ["added", "added", "checked"])

    def test_assignee_rename_with_check_is_rejected_atomically(self, world, base):
        """担当者が名前も変えるなら 403 edit_checklist。完了の切り替えも含めて何も変わらない(部分適用しない)。"""
        todo, view = base
        item = view.items[0]
        with pytest.raises(TodoPermissionDeniedError) as raised:
            update(world, world.assignee, todo, item, title="renamed", is_done=True)
        check.equal(raised.value.operation, "edit_checklist")
        row = world.item_rows(todo)[0]
        check.equal((row["title"], row["is_done"], row["version"]), ("one", False, 1))

    def test_view_only_noop_update_passes(self, world, base):
        """実際に変わる項目が無い更新(同じ名前・同じ完了状態)は、閲覧だけの人でも通り、何も変えない。"""
        todo, view = base
        item = view.items[0]
        result = update(world, world.outsider, todo, item, title="one", is_done=False)
        check.equal((result.items[0].version, result.version), (1, view.version))
        check.equal(len(world.checklist_activities(todo)), 2)

    def test_creator_rename_and_check_records_two_rows(self, world, base):
        """作成者が名前と完了を 1 回で変えると、アクティビティは renamed / checked の 2 行、項目の版は +1 を 1 回だけ。"""
        todo, view = base
        result = update(world, world.creator, todo, view.items[0], title="uno", is_done=True)
        check.equal(result.items[0].version, 2)
        rows = world.checklist_activities(todo)[-2:]
        check.equal([r["payload"]["op"] for r in rows], ["renamed", "checked"])
        check.equal(rows[0]["payload"], {"op": "renamed", "item_id": str(view.items[0].id), "title": "uno", "before": "one", "after": "uno"})

    def test_toggle_by_admin_who_is_not_assignee(self, world, base):
        """admin は担当者でなくてもチェックできる(tenant_admin)。"""
        todo, view = base
        check.is_true(update(world, world.admin, todo, view.items[1], is_done=True).items[1].is_done)


class TestNotFound:
    """閲覧できない ToDo は 404 todo_not_found、項目の特定は 404 todo_checklist_item_not_found。"""

    @pytest.fixture
    def private(self, world):
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private")
        world.factory.item(world.ctx, todo_id, world.creator)
        item_id = world.item_rows(todo_id)[0]["id"]
        return todo_id, item_id

    def all_calls(self, todo_id, item_id):
        return {
            "get": lambda s: s.get_checklist(todo_id),
            "add": lambda s: s.add_item(todo_id, title="x"),
            "update": lambda s: s.update_item(todo_id, item_id, expected_version=1, title="y"),
            "check": lambda s: s.update_item(todo_id, item_id, expected_version=1, is_done=True),
            "delete": lambda s: s.delete_item(todo_id, item_id, expected_version=1),
            "reorder": lambda s: s.reorder_items(todo_id, expected_version=1, item_ids=[item_id]),
        }

    def test_private_todo_is_hidden_from_non_viewers(self, world, private):
        """private の ToDo のチェックリストは、閲覧できない人には全操作が TodoNotFoundError。"""
        todo_id, item_id = private
        for name, func in self.all_calls(todo_id, item_id).items():
            with pytest.raises(TodoNotFoundError) as raised:
                world.checklist_call(world.outsider, func)
            check.equal(raised.value.code, "todo_not_found", name)
        check.equal([r["title"] for r in world.item_rows(todo_id)], ["item"])

    def test_deleted_todo_is_hidden_from_everyone(self, world):
        """論理削除された ToDo は管理者にも 404。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant")
        world.factory.item(world.ctx, todo_id, world.creator)
        world.call(world.creator, lambda s: s.delete_todo(todo_id, expected_version=1))
        for name, func in self.all_calls(todo_id, uuid.uuid4()).items():
            with pytest.raises(TodoNotFoundError):
                world.checklist_call(world.admin, func)

    def test_organization_todo_for_non_member(self, world):
        """organization 公開の ToDo は、公開先に属さない人には 404、属する人には見える。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1])
        with pytest.raises(TodoNotFoundError):
            get(world, world.m2, todo_id)
        check.equal(get(world, world.m1, todo_id).total_count, 0)

    def test_other_tenant_todo_even_for_admin(self, world):
        """他テナントの ToDo は、自テナントの管理者にも全操作が 404(RLS)。相手のチェックリストは変わらない。"""
        ctx = world.ap_db.tenant()
        member = world.add_person("f_member", ctx=ctx)
        foreign_todo = world.factory.add(ctx, member, visibility="tenant")
        world.factory.item(ctx, foreign_todo, member)
        foreign_item = world.item_rows(foreign_todo, ctx=ctx)[0]["id"]
        for name, func in self.all_calls(foreign_todo, foreign_item).items():
            with pytest.raises(TodoNotFoundError):
                world.checklist_call(world.admin, func)
        check.equal([r["title"] for r in world.item_rows(foreign_todo, ctx=ctx)], ["item"])

    def test_item_of_another_todo_is_not_found(self, world, todo):
        """同じテナントの別の ToDo の項目 ID は、変更・チェック・削除とも todo_checklist_item_not_found。"""
        other = world.factory.add(world.ctx, world.creator, visibility="tenant")
        world.factory.item(world.ctx, other, world.creator, title="other's")
        other_item = world.item_rows(other)[0]["id"]
        for func in (
            lambda s: s.update_item(todo, other_item, expected_version=1, title="x"),
            lambda s: s.update_item(todo, other_item, expected_version=1, is_done=True),
            lambda s: s.delete_item(todo, other_item, expected_version=1),
        ):
            with pytest.raises(TodoChecklistItemNotFoundError) as raised:
                world.checklist_call(world.admin, func)
            check.equal((raised.value.code, raised.value.todo_id, raised.value.item_id), ("todo_checklist_item_not_found", todo, other_item))
        check.equal([(r["title"], r["version"]) for r in world.item_rows(other)], [("other's", 1)])

    def test_other_tenant_item_id_on_own_todo(self, world, todo):
        """他テナントの項目 ID も todo_checklist_item_not_found(存在を明かさない)。"""
        ctx = world.ap_db.tenant()
        member = world.add_person("f_member", ctx=ctx)
        foreign_todo = world.factory.add(ctx, member)
        world.factory.item(ctx, foreign_todo, member)
        foreign_item = world.item_rows(foreign_todo, ctx=ctx)[0]["id"]
        with pytest.raises(TodoChecklistItemNotFoundError):
            world.checklist_call(world.admin, lambda s: s.delete_item(todo, foreign_item, expected_version=1))

    def test_unknown_malformed_and_deleted_item(self, world, todo):
        """存在しない・UUID でない・削除済み(物理削除)の項目 ID は todo_checklist_item_not_found。"""
        view = add(world, world.creator, todo, "gone")
        item = view.items[0]
        world.checklist_call(world.creator, lambda s: s.delete_item(todo, item.id, expected_version=item.version))
        for bad in (uuid.uuid4(), "nope", None, item.id):
            with pytest.raises(TodoChecklistItemNotFoundError):
                world.checklist_call(world.admin, lambda s, bad=bad: s.update_item(todo, bad, expected_version=1, title="x"))
            with pytest.raises(TodoChecklistItemNotFoundError):
                world.checklist_call(world.admin, lambda s, bad=bad: s.delete_item(todo, bad, expected_version=1))

    def test_malformed_todo_id(self, world):
        """UUID でない ToDo ID は todo_not_found。"""
        with pytest.raises(TodoNotFoundError):
            world.checklist_call(world.admin, lambda s: s.get_checklist("nope"))
        with pytest.raises(TodoNotFoundError):
            world.checklist_call(world.admin, lambda s: s.add_item(None, title="x"))


class TestOrderOfChecks:
    """変更系の判定の順序: 422 → 404 todo → 404 item → 412 → 403 → 422(状態に依存する検証)。"""

    @pytest.fixture
    def base(self, world, todo):
        return todo, add_many(world, world.creator, todo, ["a", "b"])

    def test_validation_beats_missing_todo(self, world):
        """項目名・位置・item_ids の形式が不正なら、ToDo が存在しなくても 422。"""
        gone = uuid.uuid4()
        for func in (
            lambda s: s.add_item(gone, title=""),
            lambda s: s.add_item(gone, title="x", position=-1),
            lambda s: s.update_item(gone, uuid.uuid4(), expected_version=1, title=" "),
            lambda s: s.update_item(gone, uuid.uuid4(), expected_version=1, is_done="yes"),
            lambda s: s.reorder_items(gone, expected_version=1, item_ids="abc"),
        ):
            with pytest.raises(TodoValidationError):
                world.checklist_call(world.admin, func)

    def test_missing_todo_beats_missing_item(self, world):
        """閲覧できない ToDo では、項目が存在しなくても todo_not_found。"""
        private = world.factory.add(world.ctx, world.creator, visibility="private")
        with pytest.raises(TodoNotFoundError):
            world.checklist_call(world.outsider, lambda s: s.delete_item(private, uuid.uuid4(), expected_version=1))

    def test_missing_item_beats_version_and_permission(self, world, todo):
        """項目が無ければ、版が違っても権限が無くても todo_checklist_item_not_found。"""
        with pytest.raises(TodoChecklistItemNotFoundError):
            world.checklist_call(world.outsider, lambda s: s.update_item(todo, uuid.uuid4(), expected_version=9, title="x"))

    def test_item_version_beats_permission(self, world, base):
        """項目の版が古い非権限者は 403 ではなく 412(target = item)。版が合えば 403。"""
        todo, view = base
        item = view.items[0]
        update(world, world.creator, todo, item, title="a2")
        for func in (
            lambda s: s.update_item(todo, item.id, expected_version=1, title="x"),
            lambda s: s.update_item(todo, item.id, expected_version=1, is_done=True),
            lambda s: s.delete_item(todo, item.id, expected_version=1),
        ):
            with pytest.raises(TodoChecklistVersionConflictError) as raised:
                world.checklist_call(world.outsider, func)
            check.equal((raised.value.code, raised.value.target, raised.value.resource_id, raised.value.expected_version, raised.value.actual_version), ("todo_checklist_version_conflict", "item", item.id, 1, 2))
        with pytest.raises(TodoPermissionDeniedError):
            world.checklist_call(world.outsider, lambda s: s.delete_item(todo, item.id, expected_version=2))

    def test_checklist_version_beats_permission_on_reorder(self, world, base):
        """並べ替えは、チェックリストの版が古ければ 403 より先に 412(target = checklist、resource_id は ToDo ID)。"""
        todo, view = base
        ids = [i.id for i in reversed(view.items)]
        with pytest.raises(TodoChecklistVersionConflictError) as raised:
            world.checklist_call(world.assignee, lambda s: s.reorder_items(todo, expected_version=view.version - 1, item_ids=ids))
        check.equal((raised.value.target, raised.value.resource_id, raised.value.expected_version, raised.value.actual_version), ("checklist", todo, view.version - 1, view.version))

    def test_permission_beats_state_dependent_validation(self, world, base):
        """権限が無い人の並べ替えは、集合が合わなくても 403(状態依存の 422 は権限の後)。権限が有れば 422 mismatch。"""
        todo, view = base
        wrong = [view.items[0].id]
        with pytest.raises(TodoPermissionDeniedError):
            world.checklist_call(world.assignee, lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=wrong))
        with pytest.raises(TodoValidationError) as raised:
            world.checklist_call(world.creator, lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=wrong))
        check.equal((raised.value.field, raised.value.reason), ("item_ids", "mismatch"))

    def test_permission_beats_too_many(self, world, todo):
        """上限に達した ToDo への追加は、権限が無い人には 403(上限の 422 は権限の後)。"""
        seed_items(world, todo, TODO_CHECKLIST_ITEMS_MAX)
        with pytest.raises(TodoPermissionDeniedError):
            add(world, world.assignee, todo, "x")
        with pytest.raises(TodoValidationError) as raised:
            add(world, world.creator, todo, "x")
        check.equal((raised.value.field, raised.value.reason), ("items", "too_many"))

    def test_item_version_is_checked_even_for_noop_update(self, world, base):
        """実際には何も変わらない更新でも、項目の版が違えば 412。"""
        todo, view = base
        with pytest.raises(TodoChecklistVersionConflictError):
            update(world, world.creator, todo, view.items[0], expected_version=7, title="a")


class TestAdd:
    """追加(AP-CHK-01 / 02 / 03)。"""

    def test_append_and_positions(self, world, todo):
        """省略すると末尾。position は 0 からの連番、項目の版は 1、作成者・更新者は操作者。checklist_version は追加ごとに +1。"""
        view = add_many(world, world.creator, todo, ["a", "b", "c"])
        check.equal((titles(view), [i.position for i in view.items], [i.version for i in view.items], view.version), (["a", "b", "c"], [0, 1, 2], [1, 1, 1], 4))
        rows = world.item_rows(todo)
        check.equal({(r["created_by"], r["updated_by"], r["is_done"], r["done_at"], r["done_by"], r["tenant_id"]) for r in rows}, {(world.creator.id, world.creator.id, False, None, None, world.ctx.tenant_id)})
        check.equal(world.todo(todo)["checklist_version"], 4)

    @pytest.mark.parametrize(
        ("position", "expected"),
        [(0, ["new", "a", "b", "c"]), (1, ["a", "new", "b", "c"]), (3, ["a", "b", "c", "new"]), (99, ["a", "b", "c", "new"]), (None, ["a", "b", "c", "new"])],
    )
    def test_insert_at_position(self, world, todo, position, expected):
        """position を指定すると、その位置に挿入して後ろをずらす。末尾より後や省略は末尾。位置は常に 0..n-1 の連番。"""
        add_many(world, world.creator, todo, ["a", "b", "c"])
        view = add(world, world.creator, todo, "new", position=position)
        check.equal((titles(view), [i.position for i in view.items]), (expected, [0, 1, 2, 3]))
        check.equal([r["position"] for r in world.item_rows(todo)], [0, 1, 2, 3])

    def test_insert_does_not_touch_other_items_versions_or_times(self, world, todo):
        """挿入で後ろにずれた既存の項目の版・更新日時は変わらない(位置の変更は項目の変更ではない)。"""
        add_many(world, world.creator, todo, ["a", "b"])
        before = {r["id"]: (r["version"], r["updated_at"]) for r in world.item_rows(todo)}
        add(world, world.creator, todo, "new", position=0)
        after = {r["id"]: (r["version"], r["updated_at"]) for r in world.item_rows(todo)}
        check.equal({k: after[k] for k in before}, before)

    @pytest.mark.parametrize(
        ("title", "reason"),
        [("", "required"), ("   ", "required"), (None, "required"), (5, "required"), ("x" * (TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH + 1), "too_long"), ("a\nb", "format"), ("a\tb", "format"), ("a\x00b", "format")],
    )
    def test_invalid_title(self, world, todo, title, reason):
        """項目名が空・空白だけ・201 文字・改行/タブ/制御文字を含む場合は TodoValidationError(field = title)。何も追加されない。"""
        with pytest.raises(TodoValidationError) as raised:
            add(world, world.creator, todo, title)
        check.equal((raised.value.field, raised.value.reason), ("title", reason))
        check.equal((world.item_rows(todo), world.todo(todo)["checklist_version"]), ([], 1))

    def test_title_boundaries_and_trim(self, world, todo):
        """200 文字ちょうどは可。前後の空白は除く(空白を除いた長さで数える)。"""
        view = add(world, world.creator, todo, "  " + "y" * TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH + " ")
        check.equal(len(view.items[0].title), TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH)
        check.equal(titles(add(world, world.creator, todo, "あ")), ["y" * 200, "あ"])

    @pytest.mark.parametrize(("position", "reason"), [(-1, "out_of_range"), ("1", "type"), (True, "type"), (1.5, "type")])
    def test_invalid_position(self, world, todo, position, reason):
        """position が負・整数でない(真偽値を含む)場合は TodoValidationError(field = position)。"""
        with pytest.raises(TodoValidationError) as raised:
            add(world, world.creator, todo, "x", position=position)
        check.equal((raised.value.field, raised.value.reason), ("position", reason))

    def test_limit_is_one_hundred(self, world, todo):
        """項目は 100 件まで: 99 件の状態で 100 件目は追加でき、101 件目は TodoValidationError(items / too_many)。件数も版も変わらない。"""
        seed_items(world, todo, TODO_CHECKLIST_ITEMS_MAX - 1)
        view = add(world, world.creator, todo, "100th")
        check.equal(view.total_count, TODO_CHECKLIST_ITEMS_MAX)
        version = world.todo(todo)["checklist_version"]
        with pytest.raises(TodoValidationError) as raised:
            add(world, world.creator, todo, "101st")
        check.equal((raised.value.field, raised.value.reason), ("items", "too_many"))
        with pytest.raises(TodoValidationError):
            add(world, world.admin, todo, "101st at top", position=0)
        check.equal((len(world.item_rows(todo)), world.todo(todo)["checklist_version"]), (TODO_CHECKLIST_ITEMS_MAX, version))

    def test_limit_is_per_todo(self, world, todo):
        """上限は ToDo ごと。別の ToDo は 100 件の ToDo があっても追加できる。"""
        seed_items(world, todo, TODO_CHECKLIST_ITEMS_MAX)
        other = world.factory.add(world.ctx, world.creator)
        check.equal(add(world, world.creator, other, "ok").total_count, 1)

    def test_position_uniqueness_is_per_todo(self, world, todo):
        """position の一意性は ToDo ごと。別の ToDo も 0 から始まる。"""
        other = world.factory.add(world.ctx, world.creator)
        add(world, world.creator, todo, "a")
        add(world, world.creator, other, "b")
        check.equal(([r["position"] for r in world.item_rows(todo)], [r["position"] for r in world.item_rows(other)]), ([0], [0]))


class TestUpdate:
    """名前変更・完了の切り替え(AP-CHK-03 / 04 / 07)。"""

    @pytest.fixture
    def base(self, world, todo):
        return todo, add_many(world, world.creator, todo, ["a", "b", "c"])

    def test_rename_bumps_item_version_only(self, world, base):
        """名前変更は項目の版 +1・更新者を操作者に。チェックリスト全体の版と他の項目は変わらない。"""
        todo, view = base
        result = update(world, world.admin, todo, view.items[1], title="  B2  ")
        check.equal((titles(result), result.items[1].version, result.version), (["a", "B2", "c"], 2, view.version))
        row = world.item_rows(todo)[1]
        check.equal((row["updated_by"], row["created_by"], row["position"]), (world.admin.id, world.creator.id, 1))
        check.equal([r["version"] for r in world.item_rows(todo)], [1, 2, 1])

    def test_check_records_done_by_and_done_at(self, world, base):
        """完了にすると done_at / done_by が入り、未完了に戻すと両方 NULL(完了の整合性)。"""
        todo, view = base
        before = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)
        done = update(world, world.assignee, todo, view.items[0], is_done=True)
        row = world.item_rows(todo)[0]
        check.equal((row["is_done"], row["done_by"], row["done_at"] >= before, row["updated_by"]), (True, world.assignee.id, True, world.assignee.id))
        check.equal((done.done_count, done.total_count), (1, 3))
        undone = update(world, world.creator, todo, done.items[0], is_done=False)
        row = world.item_rows(todo)[0]
        check.equal((row["is_done"], row["done_by"], row["done_at"], undone.done_count), (False, None, None, 0))

    def test_check_already_done_is_noop(self, world, base):
        """既に完了の項目を完了にしても何も変わらない(版・完了者・完了日時・アクティビティ・監査ログ)。"""
        todo, view = base
        done = update(world, world.assignee, todo, view.items[0], is_done=True)
        before_row, audits, activities = world.item_rows(todo)[0], len(world.todo_audits(todo)), len(world.checklist_activities(todo))
        again = update(world, world.creator, todo, done.items[0], is_done=True)
        check.equal(again.items[0].version, 2)
        check.equal(world.item_rows(todo)[0], before_row)
        check.equal((len(world.todo_audits(todo)), len(world.checklist_activities(todo))), (audits, activities))

    def test_noop_update_with_no_fields(self, world, base):
        """title も is_done も指定しない更新は何もしない(版も変えない)。"""
        todo, view = base
        result = update(world, world.creator, todo, view.items[0])
        check.equal(result.items[0].version, 1)

    @pytest.mark.parametrize(
        ("kwargs", "field", "reason"),
        [({"title": ""}, "title", "required"), ({"title": "x" * 201}, "title", "too_long"), ({"title": "a\nb"}, "title", "format"), ({"is_done": 1}, "is_done", "type"), ({"is_done": None}, "is_done", "type")],
    )
    def test_invalid_update_input(self, world, base, kwargs, field, reason):
        """項目名の検証は追加と同じ。is_done は真偽値のみ(1 や None は 422)。"""
        todo, view = base
        with pytest.raises(TodoValidationError) as raised:
            update(world, world.creator, todo, view.items[0], **kwargs)
        check.equal((raised.value.field, raised.value.reason), (field, reason))
        check.equal(world.item_rows(todo)[0]["version"], 1)

    def test_stale_item_version_is_rejected_and_nothing_changes(self, world, base):
        """古い項目の版での更新は 412。他の人が変えた内容(名前)は上書きされない。"""
        todo, view = base
        update(world, world.creator, todo, view.items[0], title="mine")
        with pytest.raises(TodoChecklistVersionConflictError) as raised:
            update(world, world.admin, todo, view.items[0], title="theirs")
        check.equal((raised.value.target, raised.value.expected_version, raised.value.actual_version), ("item", 1, 2))
        check.equal(world.item_rows(todo)[0]["title"], "mine")

    def test_item_versions_are_independent_per_item(self, world, base):
        """項目の版は項目ごと。ある項目を更新しても別の項目の版は変わらず、そちらの古い版は有効なまま。"""
        todo, view = base
        update(world, world.creator, todo, view.items[0], title="a2")
        result = update(world, world.creator, todo, view.items[1], title="b2")
        check.equal([i.version for i in result.items], [2, 2, 1])

    def test_rename_after_reorder_still_uses_item_version(self, world, base):
        """並べ替えは項目の版を変えない: 並べ替えの後も、並べ替え前に取得した項目の版で名前変更・チェックができる。"""
        todo, view = base
        world.checklist_call(world.creator, lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=[i.id for i in reversed(view.items)]))
        result = update(world, world.creator, todo, view.items[0], title="a2")
        check.equal(titles(result), ["c", "b", "a2"])


class TestDelete:
    """削除(§10 #23): 物理削除、position の詰め直し、チェックリストの版 +1、全体を返す。"""

    @pytest.mark.parametrize(("index", "expected"), [(0, ["b", "c", "d"]), (1, ["a", "c", "d"]), (3, ["a", "b", "c"])])
    def test_delete_compacts_positions(self, world, todo, index, expected):
        """先頭・中間・末尾のどれを削除しても、残りの position は 0 からの連番に詰め直される。"""
        view = add_many(world, world.creator, todo, ["a", "b", "c", "d"])
        target = view.items[index]
        result = world.checklist_call(world.creator, lambda s: s.delete_item(todo, target.id, expected_version=target.version))
        check.equal((titles(result), [i.position for i in result.items], result.total_count), (expected, [0, 1, 2], 3))
        check.equal(([r["title"] for r in world.item_rows(todo)], [r["position"] for r in world.item_rows(todo)]), (expected, [0, 1, 2]))
        check.equal((result.version, world.todo(todo)["checklist_version"]), (view.version + 1, view.version + 1))

    def test_delete_is_physical_and_returns_whole_checklist(self, world, todo):
        """行は物理削除され、応答はチェックリスト全体(進捗つき)。その項目の ID は再利用できない。"""
        view = add_many(world, world.creator, todo, ["a", "b"])
        done = update(world, world.creator, todo, view.items[1], is_done=True)
        result = world.checklist_call(world.creator, lambda s: s.delete_item(todo, done.items[0].id, expected_version=1))
        check.equal((titles(result), result.done_count, result.total_count), (["b"], 1, 1))
        check.equal(world.ap_db.rows(world.ctx, "SELECT 1 FROM t_todo_checklist_item WHERE id = :id", id=done.items[0].id), [])
        with pytest.raises(TodoChecklistItemNotFoundError):
            world.checklist_call(world.creator, lambda s: s.delete_item(todo, done.items[0].id, expected_version=1))

    def test_delete_last_item(self, world, todo):
        """最後の 1 件を削除すると空のチェックリストになる(進捗 0/0)。"""
        view = add(world, world.creator, todo, "only")
        result = world.checklist_call(world.creator, lambda s: s.delete_item(todo, view.items[0].id, expected_version=1))
        check.equal((result.items, result.total_count, result.version), ((), 0, 3))

    def test_delete_with_stale_version_is_rejected(self, world, todo):
        """古い項目の版での削除は 412(項目は残る)。"""
        view = add(world, world.creator, todo, "x")
        update(world, world.creator, todo, view.items[0], title="y")
        with pytest.raises(TodoChecklistVersionConflictError):
            world.checklist_call(world.creator, lambda s: s.delete_item(todo, view.items[0].id, expected_version=1))
        check.equal([r["title"] for r in world.item_rows(todo)], ["y"])

    def test_add_after_delete_reuses_positions(self, world, todo):
        """削除で詰めた後の追加は、次の連番(重複しない)になる。"""
        view = add_many(world, world.creator, todo, ["a", "b", "c"])
        world.checklist_call(world.creator, lambda s: s.delete_item(todo, view.items[0].id, expected_version=1))
        result = add(world, world.creator, todo, "d")
        check.equal(([i.position for i in result.items], titles(result)), ([0, 1, 2], ["b", "c", "d"]))

    def test_deleting_does_not_free_the_limit_incorrectly(self, world, todo):
        """上限(100)に達した後、1 件削除すれば再び 1 件追加できる。"""
        seed_items(world, todo, TODO_CHECKLIST_ITEMS_MAX)
        view = get(world, world.creator, todo)
        world.checklist_call(world.creator, lambda s: s.delete_item(todo, view.items[50].id, expected_version=1))
        result = add(world, world.creator, todo, "again")
        check.equal((result.total_count, [i.position for i in result.items] == list(range(100))), (100, True))


class TestReorder:
    """並べ替え(AP-CHK-03 / 07、§10 #17): 項目 ID の並びの全置換。チェックリスト全体の版で判定する。"""

    @pytest.fixture
    def base(self, world, todo):
        return todo, add_many(world, world.creator, todo, ["a", "b", "c"])

    def reorder(self, world, person, todo, version, ids):
        return world.checklist_call(person, lambda s: s.reorder_items(todo, expected_version=version, item_ids=ids))

    def test_reorder_applies_and_bumps_checklist_version(self, world, base):
        """並びが変わる並べ替えは position を振り直し、checklist_version を +1。項目の版・更新日時は変えない。"""
        todo, view = base
        before = {r["id"]: (r["version"], r["updated_at"]) for r in world.item_rows(todo)}
        ids = [view.items[2].id, view.items[0].id, view.items[1].id]
        result = self.reorder(world, world.creator, todo, view.version, ids)
        check.equal((titles(result), [i.position for i in result.items], result.version), (["c", "a", "b"], [0, 1, 2], view.version + 1))
        check.equal({r["id"]: (r["version"], r["updated_at"]) for r in world.item_rows(todo)}, before)
        check.equal(world.todo(todo)["checklist_version"], view.version + 1)

    def test_swap_two_items_in_one_transaction(self, world, todo):
        """2 件の入れ替え(DEFERRABLE の一意制約により、途中で position が重なっても 1 トランザクションで通る)。"""
        view = add_many(world, world.creator, todo, ["x", "y"])
        result = self.reorder(world, world.creator, todo, view.version, [view.items[1].id, view.items[0].id])
        check.equal((titles(result), [i.position for i in result.items]), (["y", "x"], [0, 1]))

    def test_reverse_full_hundred(self, world, todo):
        """100 件の逆順への並べ替え(位置が全て入れ替わる)でも一意制約に違反しない。"""
        seed_items(world, todo, TODO_CHECKLIST_ITEMS_MAX)
        view = get(world, world.creator, todo)
        result = self.reorder(world, world.creator, todo, view.version, [i.id for i in reversed(view.items)])
        check.equal(([i.position for i in result.items], result.items[0].title), (list(range(100)), "seed 99"))

    def test_same_order_is_noop(self, world, base):
        """現在と同じ並びは何もしない(版も監査ログも変えない)。"""
        todo, view = base
        audits = len(world.todo_audits(todo))
        result = self.reorder(world, world.creator, todo, view.version, [i.id for i in view.items])
        check.equal((result.version, len(world.todo_audits(todo))), (view.version, audits))

    def test_empty_checklist_empty_order(self, world, todo):
        """項目が無いチェックリストの空の並べ替えは何もしない。"""
        check.equal(self.reorder(world, world.creator, todo, 1, []).total_count, 0)

    def test_stale_checklist_version_is_rejected(self, world, base):
        """古いチェックリストの版は 412(target = checklist)。追加・削除でも版が上がるため、その前に取得した並びは使えない。"""
        todo, view = base
        add(world, world.creator, todo, "d")
        with pytest.raises(TodoChecklistVersionConflictError) as raised:
            self.reorder(world, world.creator, todo, view.version, [i.id for i in reversed(view.items)])
        check.equal((raised.value.target, raised.value.expected_version, raised.value.actual_version), ("checklist", view.version, view.version + 1))

    def test_item_version_cannot_be_used_for_reorder(self, world, base):
        """項目の更新(名前変更・チェック)はチェックリストの版を上げないため、その後でも並べ替えの版は有効なまま。"""
        todo, view = base
        update(world, world.creator, todo, view.items[0], title="a2")
        update(world, world.assignee, todo, view.items[1], is_done=True)
        result = self.reorder(world, world.creator, todo, view.version, [i.id for i in reversed(view.items)])
        check.equal(titles(result), ["c", "b", "a2"])

    @pytest.mark.parametrize("case", ["missing", "extra_unknown", "duplicate", "swapped_in_foreign", "too_long", "empty"])
    def test_mismatching_set_is_rejected(self, world, base, case):
        """現在の項目の集合と一致しない並び(不足・未知の ID・重複・別の ToDo の項目・101 件以上・空)は 422(item_ids / mismatch)。何も変わらない。"""
        todo, view = base
        ids = [i.id for i in view.items]
        other = world.factory.add(world.ctx, world.creator)
        world.factory.item(world.ctx, other, world.creator)
        foreign_item = world.item_rows(other)[0]["id"]
        wrong = {
            "missing": ids[:2],
            "extra_unknown": [*ids, uuid.uuid4()],
            "duplicate": [ids[0], ids[0], ids[1]],
            "swapped_in_foreign": [ids[0], ids[1], foreign_item],
            "too_long": [uuid.uuid4() for _ in range(TODO_CHECKLIST_ITEMS_MAX + 1)],
            "empty": [],
        }[case]
        with pytest.raises(TodoValidationError) as raised:
            self.reorder(world, world.creator, todo, view.version, wrong)
        check.equal((raised.value.field, raised.value.reason), ("item_ids", "mismatch"))
        check.equal(([r["title"] for r in world.item_rows(todo)], world.todo(todo)["checklist_version"]), (["a", "b", "c"], view.version))

    @pytest.mark.parametrize(("value", "reason"), [("abc", "type"), (None, "type"), (5, "type"), (["x"], "format"), ([1, 2], "format")])
    def test_malformed_item_ids(self, world, base, value, reason):
        """item_ids が配列でない・UUID でない要素を含む場合は 422(type / format)。"""
        todo, view = base
        with pytest.raises(TodoValidationError) as raised:
            self.reorder(world, world.creator, todo, view.version, value)
        check.equal((raised.value.field, raised.value.reason), ("item_ids", reason))

    def test_reorder_records_audit_but_no_activity(self, world, base):
        """並べ替えはアクティビティに記録しない。監査ログ todo.checklist_change に ops = [reordered] と版の前後を記録する。"""
        todo, view = base
        activities = world.activities(todo)
        self.reorder(world, world.admin, todo, view.version, [i.id for i in reversed(view.items)])
        check.equal(world.activities(todo), activities)
        audit = world.todo_audits(todo)[-1]
        check.equal((audit["action"], audit["actor_id"], audit["target_id"]), ("todo.checklist_change", world.admin.id, str(todo)))
        check.equal(audit["payload"], {"ops": ["reordered"], "checklist_version": {"before": view.version, "after": view.version + 1}})


class TestActivitiesAndAudit:
    """op ごとのアクティビティ(AP-ACT-05、§10 #20)と監査ログ。"""

    def test_each_operation_records_its_op(self, world, todo):
        """追加 = added、名前変更 = renamed(before / after)、完了 = checked、未完了 = unchecked、削除 = removed を 1 行ずつ。操作者・ToDo が入る。"""
        view = add(world, world.creator, todo, "first")
        item = view.items[0]
        view = update(world, world.creator, todo, item, title="renamed")
        view = update(world, world.assignee, todo, view.items[0], is_done=True)
        view = update(world, world.assignee, todo, view.items[0], is_done=False)
        world.checklist_call(world.admin, lambda s: s.delete_item(todo, item.id, expected_version=view.items[0].version))
        rows = world.checklist_activities(todo)
        check.equal([r["payload"]["op"] for r in rows], ["added", "renamed", "checked", "unchecked", "removed"])
        check.equal([r["actor_id"] for r in rows], [world.creator.id, world.creator.id, world.assignee.id, world.assignee.id, world.admin.id])
        iid = str(item.id)
        check.equal(rows[0]["payload"], {"op": "added", "item_id": iid, "title": "first"})
        check.equal(rows[1]["payload"], {"op": "renamed", "item_id": iid, "title": "renamed", "before": "first", "after": "renamed"})
        check.equal(rows[2]["payload"], {"op": "checked", "item_id": iid, "title": "renamed"})
        check.equal(rows[3]["payload"], {"op": "unchecked", "item_id": iid, "title": "renamed"})
        check.equal(rows[4]["payload"], {"op": "removed", "item_id": iid, "title": "renamed"})
        check.equal({r["tenant_id"] for r in rows}, {world.ctx.tenant_id})

    def test_activity_is_listed_for_viewers(self, world, todo):
        """checklist_changed のアクティビティは、ToDo を閲覧できる人の list_activities に action = checklist_changed で出る(新しい順)。"""
        add(world, world.creator, todo, "x")
        page = world.call(world.outsider, lambda s: s.list_activities(todo))
        check.equal([(a.action.value, a.actor_id, a.actor_display_name) for a in page.items], [("checklist_changed", world.creator.id, world.creator.name)])

    def test_audit_log_per_operation(self, world, todo):
        """監査ログ todo.checklist_change(target_type = todo)が操作ごとに残り、ops・item_id・版が入る。"""
        view = add(world, world.creator, todo, "x")
        item = view.items[0]
        update(world, world.creator, todo, item, title="y", is_done=True)
        audits = [a for a in world.todo_audits(todo) if a["action"] == "todo.checklist_change"]
        check.equal([a["target_type"] for a in audits], ["todo", "todo"])
        check.equal(audits[0]["payload"], {"ops": ["added"], "item_id": str(item.id), "position": 0, "checklist_version": {"before": 1, "after": 2}})
        check.equal(audits[1]["payload"], {"ops": ["renamed", "checked"], "item_id": str(item.id), "version": {"before": 1, "after": 2}})

    def test_rejected_operations_leave_no_trace(self, world, todo):
        """拒否された操作(403 / 412 / 422)は、アクティビティも監査ログも項目も残さない(ロールバック)。"""
        view = add(world, world.creator, todo, "x")
        activities, audits, rows = len(world.activities(todo)), len(world.todo_audits(todo)), world.item_rows(todo)
        with pytest.raises(TodoPermissionDeniedError):
            add(world, world.assignee, todo, "nope")
        with pytest.raises(TodoChecklistVersionConflictError):
            update(world, world.creator, todo, view.items[0], expected_version=5, title="z")
        with pytest.raises(TodoValidationError):
            add(world, world.creator, todo, "")
        check.equal((len(world.activities(todo)), len(world.todo_audits(todo)), world.item_rows(todo)), (activities, audits, rows))


class TestTodoIsUntouched:
    """チェックリストの変更は ToDo 本体の version / updated_at / updated_by を変えない(AP-CHK-08、§10 #16)。"""

    def test_todo_version_updated_at_updated_by_never_change(self, world, todo):
        """追加・名前変更・チェック・並べ替え・削除のどれでも、ToDo 本体の version / updated_at / updated_by は変わらない(checklist_version だけが上がる)。"""
        before = world.todo(todo)
        view = add_many(world, world.admin, todo, ["a", "b", "c"])
        view = update(world, world.admin, todo, view.items[0], title="a2")
        view = update(world, world.assignee, todo, view.items[1], is_done=True)
        view = world.checklist_call(world.creator, lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=[i.id for i in reversed(view.items)]))
        world.checklist_call(world.admin, lambda s: s.delete_item(todo, view.items[0].id, expected_version=view.items[0].version))
        after = world.todo(todo)
        check.equal((after["version"], after["updated_at"], after["updated_by"]), (before["version"], before["updated_at"], before["updated_by"]))
        check.equal(after["checklist_version"], before["checklist_version"] + 5)

    def test_todo_etag_still_valid_and_checklist_version_survives_todo_edit(self, world, todo):
        """チェックリストを変えた後でも ToDo 本体の版(If-Match)はそのまま使える。逆に ToDo を編集しても checklist_version は変わらない。"""
        add(world, world.creator, todo, "x")
        view = world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, title="renamed"))
        check.equal(view.version, 2)
        check.equal(world.todo(todo)["checklist_version"], 2)

    def test_updated_at_sort_ignores_checklist(self, world):
        """更新日時順の並びにチェックリストの操作は反映されない(§10 #16)。"""
        old = world.factory.add(world.ctx, world.creator, title="old", visibility="tenant", created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        new = world.factory.add(world.ctx, world.creator, title="new", visibility="tenant", created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))
        add(world, world.creator, old, "x")
        check.equal([t.id for t in world.call(world.admin, lambda s: s.list_todos(sort="-updated_at")).items], [new, old])

    def test_checklist_version_has_default_one_and_positive_check(self, world, todo):
        """checklist_version の既定は 1、0 以下は DB の CHECK で拒否される。"""
        from sqlalchemy import text

        check.equal(world.todo(todo)["checklist_version"], 1)
        with world.ap_db.session(world.ctx) as session:
            with pytest.raises(IntegrityError):
                session.execute(text("UPDATE t_todo SET checklist_version = 0 WHERE id = :id"), {"id": todo})
            session.rollback()


class TestDatabaseConstraints:
    """DB の制約(アプリの検証をすり抜けた場合の最終防衛線): 完了の整合性・DEFERRABLE の一意制約・複合外部キー・CHECK。"""

    def insert(self, world, todo_id, **values):
        base = {"tenant_id": world.ctx.tenant_id, "todo_id": todo_id, "title": "t", "position": 0, "created_by": world.creator.id, "updated_by": world.creator.id}
        with world.ap_db.session(world.ctx) as session:
            session.add(TTodoChecklistItem(**{**base, **values}))
            session.commit()

    @pytest.mark.parametrize(
        "values",
        [
            {"is_done": True},
            {"is_done": True, "done_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)},
            {"is_done": False, "done_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)},
        ],
    )
    def test_done_consistency_check(self, world, todo, values):
        """is_done なら done_at / done_by が必須、未完了なら両方 NULL(CHECK done_consistent)。違反は IntegrityError。"""
        with pytest.raises(IntegrityError):
            self.insert(world, todo, **values)

    def test_not_done_with_done_by_only_is_rejected(self, world, todo):
        """未完了なのに done_by だけがある行も拒否される。"""
        with pytest.raises(IntegrityError):
            self.insert(world, todo, is_done=False, done_by=world.creator.id)

    @pytest.mark.parametrize("values", [{"title": ""}, {"title": "x" * 201}, {"position": -1}, {"version": 0}])
    def test_check_constraints(self, world, todo, values):
        """項目名 1〜200 文字・position >= 0・version >= 1 の CHECK。"""
        with pytest.raises(IntegrityError):
            self.insert(world, todo, **values)

    def test_unique_position_is_enforced_at_commit(self, world, todo):
        """同じ ToDo で position が重複したままコミットすると IntegrityError(一意制約)。"""
        self.insert(world, todo, position=0)
        with pytest.raises(IntegrityError):
            self.insert(world, todo, position=0, title="dup")

    def test_unique_position_is_deferrable(self, world, todo):
        """一意制約は DEFERRABLE INITIALLY DEFERRED: 1 トランザクション内で位置を入れ替える UPDATE の途中で重なってもコミット時に解消していれば通る。"""
        from sqlalchemy import text

        row = world.ap_db.rows(world.ctx, "SELECT condeferrable, condeferred FROM pg_constraint WHERE conname = 't_todo_checklist_item_tenant_id_todo_id_position_key'")
        check.equal([(r["condeferrable"], r["condeferred"]) for r in row], [(True, True)])
        self.insert(world, todo, position=0, title="x")
        self.insert(world, todo, position=1, title="y")
        with world.ap_db.session(world.ctx) as session:
            session.execute(text("UPDATE t_todo_checklist_item SET position = 1 WHERE todo_id = :t AND title = 'x'"), {"t": todo})
            session.execute(text("UPDATE t_todo_checklist_item SET position = 0 WHERE todo_id = :t AND title = 'y'"), {"t": todo})
            session.commit()
        check.equal([r["title"] for r in world.item_rows(todo)], ["y", "x"])

    def test_composite_foreign_keys_reject_other_tenant_references(self, world, todo):
        """複合外部キー: 他テナントの ToDo・ユーザー(作成者・更新者・完了者)を指す項目は、自テナントの GUC の下でも作れない。"""
        ctx = world.ap_db.tenant()
        foreign_user = world.add_person("f_user", ctx=ctx)
        foreign_todo = world.factory.add(ctx, foreign_user)
        with pytest.raises(IntegrityError):
            self.insert(world, foreign_todo)
        for column in ("created_by", "updated_by"):
            with pytest.raises(IntegrityError):
                self.insert(world, todo, **{column: foreign_user.id})
        with pytest.raises(IntegrityError):
            self.insert(world, todo, is_done=True, done_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), done_by=foreign_user.id)
