# -*- coding: utf-8 -*-
"""ToDo のアクティビティ(AP-ACT-01..04)と AP 監査ログのテスト。

アクティビティは利用者に見せる変更履歴(``t_todo_activity``)、監査ログは基盤の ``t_ap_audit_log``。両方を変更と同じトランザクションで別々に記録する。
"""
import datetime as dt
import json
import uuid

import pytest
import pytest_check as check

from main_app.services import todo_service
from main_app.services.errors import TodoNotFoundError, TodoValidationError

SECRET = "SECRET-DESCRIPTION-BODY-ZZZ"


def kinds(world, todo_id) -> list[str]:
    """記録順のアクティビティの種別。"""
    return [a["action"] for a in world.activities(todo_id)]


class TestRecordedKinds:
    """1 回の操作で種別ごとに 1 行(AP-ACT-01)。"""

    def test_create_records_created_with_values(self, world):
        """作成は created を 1 行(作成時の値のスナップショット)。操作者・テナントが入る。"""
        view = world.call(
            world.creator,
            lambda s: s.create_todo(title="T", description="D", priority="high", due_date=dt.date(2030, 5, 6), visibility="organization", organization_ids=[world.o1], assignee_ids=[world.assignee.id]),
        )
        rows = world.activities(view.id)
        check.equal(len(rows), 1)
        check.equal((rows[0]["action"], rows[0]["actor_id"], rows[0]["tenant_id"]), ("created", world.creator.id, world.ctx.tenant_id))
        values = rows[0]["payload"]["values"]
        check.equal(
            values,
            {
                "title": "T", "description": "D", "status": "open", "priority": "high", "due_date": "2030-05-06", "visibility": "organization",
                "organization_ids": [str(world.o1)], "assignee_ids": [str(world.assignee.id)],
            },
        )

    def test_one_update_records_one_row_per_kind(self, world):
        """項目・ステータス・閲覧範囲を 1 回の PATCH で変えると、updated / status_changed / visibility_changed の 3 行(記録順)。版は +1 の 1 回だけ。"""
        todo_id = world.factory.add(world.ctx, world.creator, title="old", visibility="private")
        world.call(world.admin, lambda s: s.update_todo(todo_id, expected_version=1, title="new", status="done", visibility="organization", organization_ids=[world.o1]))
        rows = world.activities(todo_id)
        check.equal([a["action"] for a in rows], ["updated", "status_changed", "visibility_changed"])
        check.equal(len({a["created_at"] for a in rows}), 1, "同じ操作の行は同じ記録日時")
        check.equal(rows[0]["payload"], {"changes": {"title": {"before": "old", "after": "new"}}})
        check.equal(rows[1]["payload"], {"changes": {"status": {"before": "open", "after": "done"}}})
        check.equal(rows[2]["payload"], {"changes": {"visibility": {"before": "private", "after": "organization"}}, "organization_ids": {"added": [str(world.o1)], "removed": []}})
        check.equal(world.todo(todo_id)["version"], 2)

    def test_only_organizations_changed_records_visibility_changed(self, world):
        """公開先組織だけを変えると visibility_changed(organization_ids の added / removed。visibility の差分は含めない)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1])
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, organization_ids=[world.o2]))
        rows = world.activities(todo_id)
        check.equal([a["action"] for a in rows], ["visibility_changed"])
        check.equal(rows[0]["payload"], {"organization_ids": {"added": [str(world.o2)], "removed": [str(world.o1)]}})

    def test_leaving_organization_visibility_records_removed_links(self, world):
        """organization 以外に変えると公開先の行を削除し、その差分(removed)を記録する。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1, world.o2])
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, visibility="tenant"))
        payload = world.activities(todo_id)[0]["payload"]
        check.equal(payload["changes"], {"visibility": {"before": "organization", "after": "tenant"}})
        check.equal(sorted(payload["organization_ids"]["removed"]), sorted([str(world.o1), str(world.o2)]))
        check.equal(world.org_rows(todo_id), [])

    def test_delete_records_deleted(self, world):
        """削除は deleted(タイトル)を記録する。削除後も行は残る。"""
        todo_id = world.factory.add(world.ctx, world.creator, title="to delete")
        world.call(world.creator, lambda s: s.delete_todo(todo_id, expected_version=1))
        rows = world.activities(todo_id)
        check.equal([(a["action"], a["payload"]) for a in rows], [("deleted", {"title": "to delete"})])

    def test_noop_update_records_nothing(self, world):
        """値が変わらない更新はアクティビティを残さない(版も変えない)。"""
        todo_id = world.factory.add(world.ctx, world.creator, title="same")
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="same", status="open"))
        check.equal(world.activities(todo_id), [])

    def test_actions_are_the_documented_set(self, world):
        """種別は created / updated / status_changed / assignees_changed / visibility_changed / deleted の 6 つで、一通りの操作で全種別が出る。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="all"))
        world.call(world.creator, lambda s: s.update_todo(view.id, expected_version=1, title="all2", status="done", visibility="tenant"))
        world.call(world.creator, lambda s: s.set_assignees(view.id, expected_version=2, user_ids=[world.assignee.id]))
        world.call(world.creator, lambda s: s.delete_todo(view.id, expected_version=3))
        check.equal(set(kinds(world, view.id)), {"created", "updated", "status_changed", "assignees_changed", "visibility_changed", "deleted"})


class TestListActivities:
    """一覧(新しい順・カーソル・閲覧範囲)。"""

    def build(self, world):
        view = world.call(world.creator, lambda s: s.create_todo(title="a", visibility="tenant"))
        world.call(world.creator, lambda s: s.update_todo(view.id, expected_version=1, title="b"))
        world.call(world.creator, lambda s: s.update_todo(view.id, expected_version=2, title="c", status="done", priority="high"))
        world.call(world.creator, lambda s: s.set_assignees(view.id, expected_version=3, user_ids=[world.assignee.id]))
        return view.id

    def test_newest_first_and_reverse_record_order_within_operation(self, world):
        """新しい順に返り、同じ操作で記録した行は記録順の逆(§10 #15)。"""
        todo_id = self.build(world)
        page = world.call(world.creator, lambda s: s.list_activities(todo_id))
        recorded = [a["id"] for a in world.activities(todo_id)]
        check.equal([a.action.value for a in page.items], ["assignees_changed", "status_changed", "updated", "updated", "created"])
        stamps = [a.created_at for a in page.items]
        check.equal(stamps, sorted(stamps, reverse=True))
        check.equal([a.id for a in page.items], list(reversed(recorded)))
        check.is_none(page.next_after)

    def test_keyset_pagination_has_no_gaps_or_duplicates(self, world):
        """limit=2 で after を辿ると、全件が重複・欠落なく新しい順に並ぶ(同じ記録日時の行をまたいでも)。"""
        todo_id = self.build(world)
        full = [a.id for a in world.call(world.creator, lambda s: s.list_activities(todo_id)).items]
        collected, after = [], None
        for _ in range(10):
            page = world.call(world.creator, lambda s, after=after: s.list_activities(todo_id, limit=2, after=after))
            collected.extend(a.id for a in page.items)
            after = page.next_after
            if after is None:
                break
        check.equal(collected, full)
        check.equal(len(full), 5)

    def test_actor_display_name_and_view_fields(self, world):
        """操作者の ID と表示名、ToDo ID、種別(列挙型)が入る。"""
        todo_id = self.build(world)
        first = world.call(world.admin, lambda s: s.list_activities(todo_id)).items[-1]
        check.equal((first.actor_id, first.actor_display_name, first.todo_id, first.action.value), (world.creator.id, world.creator.name, todo_id, "created"))

    @pytest.mark.parametrize("after", ["x", (1, 2, 3), ("not-a-date", str(uuid.uuid4())), (dt.datetime(2026, 1, 1), str(uuid.uuid4())), (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "not-uuid")])
    def test_invalid_after_is_a_cursor_validation_error(self, world, after):
        """起点の形式が不正(日時にタイムゾーンが無い、ID が UUID でない等)なら TodoValidationError(field=cursor)。"""
        todo_id = self.build(world)
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.list_activities(todo_id, after=after))
        check.equal(caught.value.field, "cursor")

    def test_not_viewable_todo_is_not_found(self, world):
        """閲覧できない ToDo のアクティビティは TodoNotFoundError(存在しない ID と同じ)。tenant_admin・作成者・担当者は読める。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private", assignees=[world.assignee])
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="x"))
        for hidden in (world.m1, world.outsider):
            with pytest.raises(TodoNotFoundError):
                world.call(hidden, lambda s: s.list_activities(todo_id))
        for person in (world.admin, world.creator, world.assignee):
            check.equal(len(world.call(person, lambda s: s.list_activities(todo_id)).items), 1)
        with pytest.raises(TodoNotFoundError):
            world.call(world.admin, lambda s: s.list_activities(uuid.uuid4()))

    def test_deleted_todo_activities_are_not_readable(self, world):
        """削除後は誰もアクティビティを読めない(404)。行は DB に残る。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant")
        world.call(world.creator, lambda s: s.delete_todo(todo_id, expected_version=1))
        for person in (world.admin, world.creator):
            with pytest.raises(TodoNotFoundError):
                world.call(person, lambda s: s.list_activities(todo_id))
        check.equal(kinds(world, todo_id), ["deleted"])

    def test_activities_of_other_todos_are_not_mixed(self, world):
        """別の ToDo のアクティビティは含まれない。"""
        first = world.call(world.creator, lambda s: s.create_todo(title="one", visibility="tenant"))
        second = world.call(world.creator, lambda s: s.create_todo(title="two", visibility="tenant"))
        world.call(world.creator, lambda s: s.update_todo(second.id, expected_version=1, title="two2"))
        check.equal([a.action.value for a in world.call(world.creator, lambda s: s.list_activities(first.id)).items], ["created"])


class TestAuditLog:
    """AP 監査ログ(別に記録する。AP-ACT-04)。説明の本文は残さず、変更の有無だけ。"""

    def test_actions_and_targets(self, world):
        """作成 todo.create、項目・ステータス todo.update、閲覧範囲 todo.change_visibility、担当者 todo.set_assignees、削除 todo.delete を target_type=todo で残す。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="audit", description=SECRET))
        world.call(world.creator, lambda s: s.update_todo(view.id, expected_version=1, title="audit2", description=SECRET + "-2", status="done", visibility="tenant"))
        world.call(world.creator, lambda s: s.set_assignees(view.id, expected_version=2, user_ids=[world.assignee.id]))
        world.call(world.creator, lambda s: s.delete_todo(view.id, expected_version=3))
        audits = world.todo_audits(view.id)
        check.equal([a["action"] for a in audits], ["todo.create", "todo.update", "todo.change_visibility", "todo.set_assignees", "todo.delete"])
        check.equal({(a["target_type"], a["target_id"], a["actor_id"]) for a in audits}, {("todo", str(view.id), world.creator.id)})

    def test_description_body_is_not_in_audit_log(self, world):
        """説明の本文は監査ログのどのレコードにも残らない(作成・更新・削除)。更新では description の変更の有無(changed)だけを残す。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="audit", description=SECRET))
        world.call(world.creator, lambda s: s.update_todo(view.id, expected_version=1, description=SECRET + "-changed"))
        world.call(world.creator, lambda s: s.delete_todo(view.id, expected_version=2))
        audits = world.todo_audits(view.id)
        check.is_not_in(SECRET, json.dumps([a["payload"] for a in audits], ensure_ascii=False))
        update = next(a for a in audits if a["action"] == "todo.update")
        check.equal(update["payload"]["changes"], {"description": {"changed": True}})
        create = next(a for a in audits if a["action"] == "todo.create")
        check.is_not_in("description", create["payload"])

    def test_activity_and_audit_are_separate_records(self, world):
        """アクティビティと監査ログは別のテーブルに別々に記録する(アクティビティに監査ログの行は含まれず、逆も同じ)。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="x"))
        check.equal(len(world.activities(view.id)), 1)
        check.equal(len(world.todo_audits(view.id)), 1)
        check.is_not_in("todo.create", [a["action"] for a in world.activities(view.id)])

    def test_update_audit_payload(self, world):
        """todo.update の payload は項目とステータスの差分と版。todo.change_visibility の payload は閲覧範囲の差分と版。"""
        todo_id = world.factory.add(world.ctx, world.creator, title="old")
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="new", status="in_progress", visibility="tenant"))
        audits = {a["action"]: a["payload"] for a in world.todo_audits(todo_id)}
        check.equal(audits["todo.update"]["changes"], {"title": {"before": "old", "after": "new"}, "status": {"before": "open", "after": "in_progress"}})
        check.equal(audits["todo.update"]["version"], {"before": 1, "after": 2})
        check.equal(audits["todo.change_visibility"]["changes"], {"visibility": {"before": "private", "after": "tenant"}})

    def test_status_only_change_has_no_visibility_audit(self, world):
        """ステータスだけの変更は todo.update だけ(todo.change_visibility は残さない)。"""
        todo_id = world.factory.add(world.ctx, world.creator)
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, status="done"))
        check.equal([a["action"] for a in world.todo_audits(todo_id)], ["todo.update"])

    def test_audit_log_is_not_readable_via_activities(self, world):
        """監査ログの行(target_type=todo)は、ToDo のアクティビティ一覧に現れない。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="x", visibility="tenant"))
        page = world.call(world.creator, lambda s: s.list_activities(view.id))
        check.equal([a.action.value for a in page.items], ["created"])


class TestAtomicity:
    """変更・アクティビティ・監査ログは同じトランザクション(AP-ACT-03)。"""

    def test_failure_after_recording_rolls_back_everything(self, world, monkeypatch):
        """記録の途中で失敗したら、ToDo の変更もアクティビティも監査ログもすべてロールバックされる。"""
        todo_id = world.factory.add(world.ctx, world.creator, title="before")

        def boom(*args, **kwargs):
            raise RuntimeError("audit failed")

        monkeypatch.setattr(todo_service, "record_audit", boom)
        with pytest.raises(RuntimeError):
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="after", status="done"))
        row = world.todo(todo_id)
        check.equal((row["title"], row["status"], row["version"]), ("before", "open", 1))
        check.equal(world.activities(todo_id), [])

    def test_failed_create_leaves_no_rows(self, world, monkeypatch):
        """作成の途中で失敗したら、ToDo・公開先・担当者・アクティビティのどれも残らない。"""
        monkeypatch.setattr(todo_service, "record_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit failed")))
        with pytest.raises(RuntimeError):
            world.call(world.creator, lambda s: s.create_todo(title="ghost", visibility="organization", organization_ids=[world.o1], assignee_ids=[world.assignee.id]))
        for table in ("t_todo", "t_todo_organization", "t_todo_assignee", "t_todo_activity"):
            check.equal(world.ap_db.rows(world.ctx, f"SELECT 1 FROM {table}"), [], table)
