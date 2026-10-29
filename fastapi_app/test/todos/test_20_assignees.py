# -*- coding: utf-8 -*-
"""ToDo の担当者(AP-ASN-01..05)のテスト。最大 20 人、無効ユーザーの新規割り当て禁止、他テナントのユーザー、``assigned_at`` の維持。"""
import datetime as dt
import uuid

import pytest
import pytest_check as check
from sqlalchemy.exc import IntegrityError

from main_app.models import TTodoAssignee
from main_app.services.errors import InvalidTodoAssigneesError, TodoNotFoundError, TodoPermissionDeniedError, TodoValidationError, TodoVersionConflictError


@pytest.fixture
def todo(world):
    """tenant 公開の ToDo(作成者は creator、担当者は assignee のみ)。"""
    return world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.assignee], assigned_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))


def users(world, count: int) -> list:
    return [world.add_person(f"extra{index}") for index in range(count)]


class TestLimit:
    """AP-ASN-01: 最大 20 人。"""

    def test_twenty_is_allowed_and_twenty_one_is_not(self, world, todo):
        """20 人までは設定でき、21 人は TodoValidationError(user_ids / too_many)。拒否したときは何も変わらない。"""
        people = users(world, 21)
        view = world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[p.id for p in people[:20]]))
        check.equal(len(view.assignees), 20)
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=2, user_ids=[p.id for p in people]))
        check.equal((caught.value.field, caught.value.reason), ("user_ids", "too_many"))
        check.equal(len(world.assignee_rows(todo)), 20)
        check.equal(world.todo(todo)["version"], 2)

    def test_duplicates_are_collapsed_before_counting(self, world, todo):
        """重複は 1 人として数える(同じ ID を 25 回送っても 1 人)。"""
        person = users(world, 1)[0]
        view = world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[person.id] * 25))
        check.equal([a.user_id for a in view.assignees], [person.id])

    def test_create_with_more_than_twenty_is_rejected(self, world):
        """作成時も 21 人は TodoValidationError(assignee_ids / too_many)で、ToDo は作られない。"""
        people = users(world, 21)
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.create_todo(title="t", assignee_ids=[p.id for p in people]))
        check.equal((caught.value.field, caught.value.reason), ("assignee_ids", "too_many"))
        check.equal(world.ap_db.rows(world.ctx, "SELECT id FROM t_todo WHERE title = 't'"), [])


class TestNewAssignmentsAreValidated:
    """AP-ASN-02: 他テナントのユーザー、無効化されたユーザーは新たに割り当てられない。"""

    def test_inactive_user_cannot_be_newly_assigned(self, world, todo):
        """無効化されたユーザーの新規割り当ては InvalidTodoAssigneesError(reason=inactive、user_ids 付き)。何も変わらない。"""
        with pytest.raises(InvalidTodoAssigneesError) as caught:
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[world.assignee.id, world.inactive.id]))
        check.equal((caught.value.reason, caught.value.user_ids, caught.value.field, caught.value.code), ("inactive", (world.inactive.id,), "user_ids", "invalid_todo_assignees"))
        check.equal([r["user_id"] for r in world.assignee_rows(todo)], [world.assignee.id])
        check.equal(world.todo(todo)["version"], 1)

    def test_unknown_and_other_tenant_users_are_not_found(self, world, todo):
        """存在しないユーザー・他テナントのユーザーは reason=not_found(区別しない)。他テナントのユーザーは割り当てられない。"""
        other = world.ap_db.tenant()
        foreign = world.ap_db.add_user(other)
        ghost = uuid.uuid4()
        with pytest.raises(InvalidTodoAssigneesError) as caught:
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[world.assignee.id, foreign.id, ghost]))
        check.equal((caught.value.reason, set(caught.value.user_ids)), ("not_found", {foreign.id, ghost}))
        check.equal([r["user_id"] for r in world.assignee_rows(todo)], [world.assignee.id])
        check.equal(world.ap_db.rows(other, "SELECT * FROM t_todo_assignee"), [])

    def test_not_found_takes_precedence_over_inactive(self, world, todo):
        """存在しないユーザーと無効なユーザーが混ざる場合は not_found を先に報告する。"""
        with pytest.raises(InvalidTodoAssigneesError) as caught:
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[world.inactive.id, uuid.uuid4()]))
        check.equal(caught.value.reason, "not_found")

    def test_create_validates_assignees_too(self, world):
        """作成時も無効なユーザー・他テナントのユーザーは 422 相当(field は assignee_ids)で、ToDo もアクティビティも作られない。"""
        other = world.ap_db.tenant()
        foreign = world.ap_db.add_user(other)
        for user_id, reason in ((world.inactive.id, "inactive"), (foreign.id, "not_found")):
            with pytest.raises(InvalidTodoAssigneesError) as caught:
                world.call(world.creator, lambda s, user_id=user_id: s.create_todo(title="never", assignee_ids=[user_id]))
            check.equal((caught.value.reason, caught.value.field), (reason, "assignee_ids"))
        check.equal(world.ap_db.rows(world.ctx, "SELECT id FROM t_todo WHERE title = 'never'"), [])
        check.equal(world.ap_db.rows(world.ctx, "SELECT id FROM t_todo_activity"), [])

    def test_composite_foreign_key_blocks_other_tenant_user_at_db_level(self, world, todo):
        """事前チェックが無くても、複合外部キーで他テナントのユーザーは担当者の行にできない(DB の多重防御)。"""
        foreign = world.ap_db.add_user(world.ap_db.tenant())
        with world.ap_db.session(world.ctx) as session:
            session.add(TTodoAssignee(tenant_id=world.ctx.tenant_id, todo_id=todo, user_id=foreign.id, assigned_by=world.creator.id))
            with pytest.raises(IntegrityError):
                session.commit()


class TestInactiveAssignees:
    """AP-ASN-04: 既に割り当て済みの無効ユーザーは残る・外せる。"""

    def test_existing_inactive_assignee_can_stay(self, world):
        """既に担当者の無効ユーザーを残したまま別の担当者を追加できる(新規ではないので 422 にならない)。無効ユーザーの行は維持される。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.inactive])
        new = users(world, 1)[0]
        view = world.call(world.creator, lambda s: s.set_assignees(todo_id, expected_version=1, user_ids=[world.inactive.id, new.id]))
        check.equal({(a.user_id, a.is_active) for a in view.assignees}, {(world.inactive.id, False), (new.id, True)})

    def test_existing_inactive_assignee_can_be_removed(self, world):
        """作成者・tenant_admin は、無効ユーザーの担当者を外せる。"""
        for actor in (world.creator, world.admin):
            todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.inactive, world.assignee])
            view = world.call(actor, lambda s, todo_id=todo_id: s.set_assignees(todo_id, expected_version=1, user_ids=[world.assignee.id]))
            check.equal([a.user_id for a in view.assignees], [world.assignee.id])

    def test_assignee_deactivated_after_assignment_remains_listed(self, world, todo):
        """割り当て後にユーザーが無効化されても、割り当ては残り、is_active=False で表示される(一覧・詳細とも)。"""
        with world.ap_db.session(world.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_user SET is_active = false WHERE id = %s", (world.assignee.id,))
            session.commit()
        detail = world.call(world.creator, lambda s: s.get_todo(todo))
        listed = world.call(world.creator, lambda s: s.list_todos()).items[0]
        check.equal([(a.user_id, a.is_active) for a in detail.assignees], [(world.assignee.id, False)])
        check.equal([(a.user_id, a.is_active) for a in listed.assignees], [(world.assignee.id, False)])

    def test_no_change_with_inactive_assignee_is_a_noop(self, world):
        """無効な担当者を含む現在の集合と同じ集合を送るのは変更なし(422 にならず、版も変わらない)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.inactive])
        view = world.call(world.creator, lambda s: s.set_assignees(todo_id, expected_version=1, user_ids=[world.inactive.id]))
        check.equal(view.version, 1)


class TestReplaceSemantics:
    """AP-ASN-05: 担当者の集合の全置換。残る担当者の行は維持する。"""

    def test_assigned_at_and_assigned_by_are_kept_for_remaining(self, world, todo):
        """残る担当者の assigned_at / assigned_by は変わらない。新しい担当者には、操作者と現在時刻が入る。"""
        original = world.assignee_rows(todo)[0]
        new = users(world, 1)[0]
        before = dt.datetime.now(dt.UTC)
        world.call(world.admin, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[world.assignee.id, new.id]))
        rows = {r["user_id"]: r for r in world.assignee_rows(todo)}
        check.equal(rows[world.assignee.id]["assigned_at"], original["assigned_at"])
        check.equal(rows[world.assignee.id]["assigned_by"], original["assigned_by"])
        check.equal(rows[new.id]["assigned_by"], world.admin.id)
        check.greater_equal(rows[new.id]["assigned_at"], before)

    def test_replace_adds_and_removes(self, world, todo):
        """集合を置き換えると、新しい担当者が増え、含まれない担当者は外れる。版は +1、updated_by は操作者。"""
        a, b = users(world, 2)
        view = world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[a.id, b.id]))
        check.equal({x.user_id for x in view.assignees}, {a.id, b.id})
        row = world.todo(todo)
        check.equal((row["version"], row["updated_by"]), (2, world.creator.id))

    def test_empty_list_removes_everyone(self, world, todo):
        """空の配列で全員を外せる。"""
        view = world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[]))
        check.equal(view.assignees, ())

    def test_noop_does_not_bump_version_or_record(self, world, todo):
        """同じ集合(順序違い・重複を含む)の置き換えは何もしない: 版・アクティビティ・監査ログを増やさない。"""
        view = world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[world.assignee.id, world.assignee.id]))
        check.equal(view.version, 1)
        check.equal((world.activities(todo), world.todo_audits(todo)), ([], []))

    def test_assignee_can_change_assignees_and_remove_self(self, world, todo):
        """担当者は担当者を変更できる。自分を外して閲覧できなくなった場合も、その応答は返り、以降は 404 になる(tenant 公開でなければ)。"""
        private = world.factory.add(world.ctx, world.creator, visibility="private", assignees=[world.assignee])
        other = users(world, 1)[0]
        view = world.call(world.assignee, lambda s: s.set_assignees(private, expected_version=1, user_ids=[other.id]))
        check.equal([a.user_id for a in view.assignees], [other.id])
        with pytest.raises(TodoNotFoundError):
            world.call(world.assignee, lambda s: s.get_todo(private))

    def test_viewer_without_permission_gets_403(self, world, todo):
        """担当者でも作成者でも tenant_admin でもない閲覧者は 403(change_assignees)。"""
        with pytest.raises(TodoPermissionDeniedError) as caught:
            world.call(world.m1, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[world.m1.id]))
        check.equal(caught.value.operation, "change_assignees")

    def test_stale_version_conflict(self, world, todo):
        """版が違えば TodoVersionConflictError。"""
        with pytest.raises(TodoVersionConflictError):
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=4, user_ids=[]))

    @pytest.mark.parametrize("value", ["abc", None, 5, ["not-uuid"], [str(uuid.uuid4())], [None]])
    def test_invalid_user_ids_shape(self, world, todo, value):
        """user_ids の型・形式が不正なら TodoValidationError(user_ids)。"""
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=value))
        check.equal(caught.value.field, "user_ids")

    def test_assignee_gains_visibility_of_private_todo(self, world):
        """担当者にされたユーザーは、private な ToDo を閲覧できるようになる(外されると見えなくなる)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private")
        with pytest.raises(TodoNotFoundError):
            world.call(world.outsider, lambda s: s.get_todo(todo_id))
        world.call(world.creator, lambda s: s.set_assignees(todo_id, expected_version=1, user_ids=[world.outsider.id]))
        check.is_not_none(world.call(world.outsider, lambda s: s.get_todo(todo_id)))
        world.call(world.creator, lambda s: s.set_assignees(todo_id, expected_version=2, user_ids=[]))
        with pytest.raises(TodoNotFoundError):
            world.call(world.outsider, lambda s: s.get_todo(todo_id))


class TestRecords:
    """担当者の変更のアクティビティと監査ログ。"""

    def test_activity_and_audit_for_change(self, world, todo):
        """担当者の変更は、アクティビティ assignees_changed(added / removed)と監査ログ todo.set_assignees を同じトランザクションで残す。"""
        new = users(world, 1)[0]
        world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[new.id]))
        activities = world.activities(todo)
        check.equal([(a["action"], a["actor_id"]) for a in activities], [("assignees_changed", world.creator.id)])
        check.equal(activities[0]["payload"], {"added": [str(new.id)], "removed": [str(world.assignee.id)]})
        audits = world.todo_audits(todo)
        check.equal([a["action"] for a in audits], ["todo.set_assignees"])
        check.equal(audits[0]["payload"]["added"], [str(new.id)])
        check.equal(audits[0]["payload"]["version"], {"before": 1, "after": 2})
        check.equal(audits[0]["actor_id"], world.creator.id)

    def test_failed_change_records_nothing(self, world, todo):
        """失敗した(422 / 403 / 412)担当者の変更は、アクティビティも監査ログも残さない。"""
        for actor, kwargs in ((world.creator, {"user_ids": [world.inactive.id]}), (world.m1, {"user_ids": []}), (world.creator, {"user_ids": [], "expected_version": 9})):
            kwargs.setdefault("expected_version", 1)
            with pytest.raises((InvalidTodoAssigneesError, TodoPermissionDeniedError, TodoVersionConflictError)):
                world.call(actor, lambda s, kwargs=kwargs: s.set_assignees(todo, **kwargs))
        check.equal((world.activities(todo), world.todo_audits(todo)), ([], []))
