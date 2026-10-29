# -*- coding: utf-8 -*-
"""ToDo のコメント(AP-CMT-01..08、ToDoApp.md §9.3 / §10 #16・#19・#24)のサービス層のテスト。実サービス + 実 DB(RLS)。

観点: 閲覧できない人の 404、他テナント・別 ToDo のコメントの 404、権限(投稿者 / tenant_admin / それ以外)、楽観ロック(412)、判定の順序
(422 → 404 todo → 404 comment → 412 → 403)、古い順とカーソル、論理削除、無効化された投稿者、監査ログに本文が無いこと、
アクティビティを増やさないこと、ToDo 本体の ``version`` / ``updated_at`` を変えないこと。
"""
import concurrent.futures
import datetime as dt
import threading
import uuid

import pytest
import pytest_check as check

from main_app.models.todo import TODO_COMMENT_BODY_MAX_LENGTH
from main_app.services.errors import TodoCommentNotFoundError, TodoCommentVersionConflictError, TodoNotFoundError, TodoPermissionDeniedError, TodoValidationError

BODY = "SECRET-COMMENT-BODY-QQQ"


def datetime_now() -> dt.datetime:
    """編集日時の下限の確認用(5 秒前。時計のずれに備える)。"""
    return dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)


@pytest.fixture
def todo(world):
    """テナント全体に公開された ToDo(作成者 = creator)。誰でも閲覧・コメントできる。"""
    return world.factory.add(world.ctx, world.creator, title="open to all", visibility="tenant")


@pytest.fixture
def private_todo(world):
    """private の ToDo(作成者 = creator、担当者 = assignee)。admin・creator・assignee だけが閲覧できる。"""
    return world.factory.add(world.ctx, world.creator, title="private", visibility="private", assignees=[world.assignee])


def post(world, person, todo_id, body="hello"):
    return world.comments_call(person, lambda s: s.create_comment(todo_id, body=body))


class TestPost:
    """投稿(AP-CMT-01): ToDo を閲覧できれば誰でもできる。"""

    @pytest.mark.parametrize("who", ["creator", "assignee", "admin", "outsider", "m1", "m2"])
    def test_anyone_who_can_view_can_post(self, world, todo, who):
        """tenant 公開の ToDo には、作成者・担当者・管理者・組織に属さない member も投稿できる。投稿者は操作者。"""
        person = world.people[who]
        view = post(world, person, todo, "  確認しました  ")
        check.equal((view.body, view.author.id, view.author.display_name, view.author.is_active, view.todo_id), ("確認しました", person.id, person.name, True, todo))
        check.equal((view.version, view.edited_at), (1, None))
        check.equal((view.permissions.can_edit, view.permissions.can_delete), (True, True))
        row = world.comment_rows(todo)[0]
        check.equal((row["tenant_id"], row["author_id"], row["deleted_at"], row["id"].version), (world.ctx.tenant_id, person.id, None, 7))

    @pytest.mark.parametrize("who", ["creator", "assignee", "admin"])
    def test_private_todo_viewers_can_post(self, world, private_todo, who):
        """private の ToDo には、作成者・担当者・管理者が投稿できる。"""
        view = post(world, world.people[who], private_todo)
        check.equal(view.author.id, world.people[who].id)

    def test_organization_member_can_post_when_visible(self, world):
        """organization 公開の ToDo には、公開先の組織の所属者が投稿できる。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1])
        check.equal(post(world, world.m1, todo_id).author.id, world.m1.id)

    @pytest.mark.parametrize(
        ("body", "field_reason"),
        [
            ("", ("body", "required")),
            ("   \n\t ", ("body", "required")),
            (None, ("body", "required")),
            (123, ("body", "required")),
            ("x" * (TODO_COMMENT_BODY_MAX_LENGTH + 1), ("body", "too_long")),
            ("a\x00b", ("body", "format")),
            ("a\x1bb", ("body", "format")),
            ("a\x7fb", ("body", "format")),
        ],
    )
    def test_invalid_body_is_rejected(self, world, todo, body, field_reason):
        """本文が空・空白だけ・4,000 文字超・改行とタブ以外の制御文字を含むと TodoValidationError(何も保存しない)。"""
        with pytest.raises(TodoValidationError) as raised:
            post(world, world.creator, todo, body)
        check.equal((raised.value.field, raised.value.reason), field_reason)
        check.equal(world.comment_rows(), [])

    def test_body_boundaries_are_accepted(self, world, todo):
        """1 文字と 4,000 文字ちょうど、改行・タブを含む本文は投稿できる。前後の空白を除いた長さで数える。"""
        one = post(world, world.creator, todo, "a")
        full = post(world, world.creator, todo, "x" * TODO_COMMENT_BODY_MAX_LENGTH)
        padded = post(world, world.creator, todo, "  " + "y" * TODO_COMMENT_BODY_MAX_LENGTH + "  ")
        multi = post(world, world.creator, todo, "line1\nline2\ttab\r\nline3")
        check.equal((len(one.body), len(full.body), len(padded.body), multi.body), (1, 4000, 4000, "line1\nline2\ttab\r\nline3"))


class TestInvisibleTodo:
    """閲覧できない ToDo のコメントは、一覧・投稿・編集・削除のすべてが 404 todo_not_found(存在を明かさない。AP-CMT-06)。"""

    def assert_all_not_found(self, world, person, todo_id, comment_id, *, version=1):
        calls = {
            "list": lambda s: s.list_comments(todo_id),
            "create": lambda s: s.create_comment(todo_id, body="x"),
            "update": lambda s: s.update_comment(todo_id, comment_id, expected_version=version, body="y"),
            "delete": lambda s: s.delete_comment(todo_id, comment_id, expected_version=version),
        }
        for name, func in calls.items():
            with pytest.raises(TodoNotFoundError) as raised:
                world.comments_call(person, func)
            check.equal(raised.value.code, "todo_not_found", name)

    def test_private_todo_hides_comments_from_others(self, world, private_todo):
        """private の ToDo のコメントは、作成者でも担当者でもない member には 4 操作とも 404。"""
        comment_id = world.factory.comment(world.ctx, private_todo, world.creator, body=BODY)
        self.assert_all_not_found(world, world.outsider, private_todo, comment_id)
        check.equal(len(world.comment_rows(private_todo)), 1, "何も書き込まれていない")

    def test_organization_todo_hides_comments_from_non_members(self, world):
        """organization 公開の ToDo は、公開先に所属しない人(別の組織の人)には 404。所属する人には見える。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1])
        comment_id = world.factory.comment(world.ctx, todo_id, world.creator)
        self.assert_all_not_found(world, world.m2, todo_id, comment_id)
        check.equal([c.id for c in world.comments_call(world.m1, lambda s: s.list_comments(todo_id)).items], [comment_id])

    def test_organization_todo_with_all_orgs_deleted_is_private(self, world):
        """公開先の組織がすべて削除された organization の ToDo は private と同じ(AP-VIS-08)。元の組織の所属者でもコメントできない。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o3])
        comment_id = world.factory.comment(world.ctx, todo_id, world.creator)
        self.assert_all_not_found(world, world.n3, todo_id, comment_id)
        check.equal(len(world.comments_call(world.creator, lambda s: s.list_comments(todo_id)).items), 1)

    def test_comment_author_who_lost_visibility_cannot_touch_own_comment(self, world, todo):
        """投稿者が閲覧範囲から外れると、自分のコメントも 404(コメントは残る。AP-CMT-06 / 07)。"""
        comment_id = post(world, world.outsider, todo).id
        world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, visibility="private"))
        self.assert_all_not_found(world, world.outsider, todo, comment_id)
        check.equal([row["deleted_at"] for row in world.comment_rows(todo)], [None])

    def test_deleted_todo_hides_comments_from_everyone(self, world, todo):
        """ToDo を削除(論理削除)した後は、管理者・作成者を含め誰でも 4 操作とも 404。コメントの行は残る。"""
        comment_id = post(world, world.creator, todo).id
        world.call(world.creator, lambda s: s.delete_todo(todo, expected_version=1))
        for person in (world.admin, world.creator, world.outsider):
            self.assert_all_not_found(world, person, todo, comment_id)
        check.equal(len(world.comment_rows(todo)), 1)

    def test_nonexistent_and_malformed_todo_ids(self, world):
        """存在しない ToDo ID・UUID でない値も todo_not_found(閲覧できない場合と区別しない)。"""
        for bad in (uuid.uuid4(), "not-a-uuid", None):
            with pytest.raises(TodoNotFoundError):
                world.comments_call(world.admin, lambda s, bad=bad: s.list_comments(bad))
            with pytest.raises(TodoNotFoundError):
                world.comments_call(world.admin, lambda s, bad=bad: s.update_comment(bad, uuid.uuid4(), expected_version=1, body="x"))


class TestCrossTenant:
    """他テナントの ToDo・コメントは存在しない扱い(404)。書き込みもできない。"""

    @pytest.fixture
    def foreign(self, world):
        """別の使い捨てテナント(管理者・member・ToDo・コメント付き)。"""
        ctx = world.ap_db.tenant()
        admin = world.add_person("f_admin", roles=("tenant_admin",), ctx=ctx)
        member = world.add_person("f_member", ctx=ctx)
        todo_id = world.factory.add(ctx, member, title="foreign", visibility="tenant")
        comment_id = world.factory.comment(ctx, todo_id, member, body="foreign comment")
        return ctx, admin, member, todo_id, comment_id

    def test_other_tenant_todo_id_is_not_found_even_for_admin(self, world, foreign):
        """自テナントの管理者でも、他テナントの todo_id は 4 操作とも TodoNotFoundError(todo_not_found)。"""
        _, _, _, foreign_todo, foreign_comment = foreign
        TestInvisibleTodo().assert_all_not_found(world, world.admin, foreign_todo, foreign_comment)

    def test_nothing_changes_in_the_other_tenant(self, world, foreign):
        """他テナントへの操作の試行は、相手テナントのコメントを変えない・増やさない。"""
        ctx, _, _, foreign_todo, foreign_comment = foreign
        before = world.comment_rows(foreign_todo, ctx=ctx)
        TestInvisibleTodo().assert_all_not_found(world, world.admin, foreign_todo, foreign_comment)
        check.equal(world.comment_rows(foreign_todo, ctx=ctx), before)

    def test_other_tenant_comment_id_on_own_todo_is_comment_not_found(self, world, todo, foreign):
        """自テナントの閲覧できる ToDo に、他テナントの comment_id を指定すると TodoCommentNotFoundError(存在を明かさない)。"""
        _, _, _, _, foreign_comment = foreign
        with pytest.raises(TodoCommentNotFoundError) as raised:
            world.comments_call(world.admin, lambda s: s.update_comment(todo, foreign_comment, expected_version=1, body="x"))
        check.equal((raised.value.code, raised.value.comment_id), ("todo_comment_not_found", foreign_comment))
        with pytest.raises(TodoCommentNotFoundError):
            world.comments_call(world.admin, lambda s: s.delete_comment(todo, foreign_comment, expected_version=1))

    def test_each_tenant_lists_only_its_own_comments(self, world, todo, foreign):
        """各テナントのコメント一覧には自テナントのコメントだけが出る。"""
        ctx, admin, _, foreign_todo, _ = foreign
        mine = post(world, world.creator, todo, "mine").id
        theirs = world.comments_call(admin, lambda s: s.list_comments(foreign_todo), ctx=ctx)
        check.equal([c.body for c in theirs.items], ["foreign comment"])
        check.equal([c.id for c in world.comments_call(world.admin, lambda s: s.list_comments(todo)).items], [mine])

    def test_composite_foreign_key_rejects_cross_tenant_rows(self, world, foreign):
        """DB の複合外部キー: 自テナントの GUC の下でも、他テナントの ToDo・ユーザーを指すコメントは作れない(アプリのバグの最終防衛)。"""
        from sqlalchemy.exc import IntegrityError

        from main_app.models import TTodoComment

        _, _, foreign_member, foreign_todo, _ = foreign
        for todo_id, author_id in ((foreign_todo, world.creator.id), (world.factory.add(world.ctx, world.creator), foreign_member.id)):
            with world.ap_db.session(world.ctx) as session:
                session.add(TTodoComment(tenant_id=world.ctx.tenant_id, todo_id=todo_id, author_id=author_id, body="x"))
                with pytest.raises(IntegrityError):
                    session.commit()


class TestCommentLookup:
    """コメントの特定(別の ToDo のコメント・存在しない・削除済み → 404 todo_comment_not_found)。"""

    def test_comment_of_another_todo_in_same_tenant(self, world, todo):
        """同じテナントの別の ToDo のコメントの ID を指定すると、編集・削除とも TodoCommentNotFoundError(todo_comment_not_found)。コメントは変わらない。"""
        other_todo = world.factory.add(world.ctx, world.creator, visibility="tenant")
        other_comment = world.factory.comment(world.ctx, other_todo, world.creator, body="other todo")
        with pytest.raises(TodoCommentNotFoundError) as raised:
            world.comments_call(world.creator, lambda s: s.update_comment(todo, other_comment, expected_version=1, body="x"))
        check.equal((raised.value.code, raised.value.todo_id, raised.value.comment_id), ("todo_comment_not_found", todo, other_comment))
        with pytest.raises(TodoCommentNotFoundError):
            world.comments_call(world.creator, lambda s: s.delete_comment(todo, other_comment, expected_version=1))
        check.equal([(r["body"], r["version"], r["deleted_at"]) for r in world.comment_rows(other_todo)], [("other todo", 1, None)])

    def test_unknown_and_malformed_comment_id(self, world, todo):
        """存在しないコメント ID・UUID でない値も todo_comment_not_found。"""
        for bad in (uuid.uuid4(), "nope", None):
            with pytest.raises(TodoCommentNotFoundError):
                world.comments_call(world.admin, lambda s, bad=bad: s.update_comment(todo, bad, expected_version=1, body="x"))
            with pytest.raises(TodoCommentNotFoundError):
                world.comments_call(world.admin, lambda s, bad=bad: s.delete_comment(todo, bad, expected_version=1))

    def test_deleted_comment_cannot_be_edited_or_deleted_again(self, world, todo):
        """論理削除済みのコメントは、編集も再削除も todo_comment_not_found(誰でも、管理者でも)。"""
        comment = post(world, world.creator, todo)
        world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=1))
        for person in (world.creator, world.admin):
            with pytest.raises(TodoCommentNotFoundError):
                world.comments_call(person, lambda s: s.update_comment(todo, comment.id, expected_version=2, body="x"))
            with pytest.raises(TodoCommentNotFoundError):
                world.comments_call(person, lambda s: s.delete_comment(todo, comment.id, expected_version=2))


class TestPermissions:
    """編集は投稿者のみ、削除は投稿者と tenant_admin(AP-CMT-03 / 04)。"""

    @pytest.fixture
    def comment(self, world, todo):
        return post(world, world.m1, todo, "by m1")

    def test_author_can_edit_and_delete_own(self, world, todo, comment):
        """投稿者は自分のコメントを編集・削除できる(投稿者が member でも)。"""
        edited = world.comments_call(world.m1, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="edited"))
        check.equal((edited.body, edited.version), ("edited", 2))
        world.comments_call(world.m1, lambda s: s.delete_comment(todo, comment.id, expected_version=2))
        check.is_not_none(world.comment_rows(todo)[0]["deleted_at"])

    @pytest.mark.parametrize("who", ["creator", "assignee", "m2", "outsider"])
    def test_other_members_cannot_edit_or_delete(self, world, todo, comment, who):
        """他の member(ToDo の作成者・担当者を含む)は編集・削除とも 403 todo_operation_forbidden(operation = edit_comment / delete_comment)。"""
        person = world.people[who]
        with pytest.raises(TodoPermissionDeniedError) as raised:
            world.comments_call(person, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="hack"))
        check.equal((raised.value.code, raised.value.operation), ("todo_operation_forbidden", "edit_comment"))
        with pytest.raises(TodoPermissionDeniedError) as raised:
            world.comments_call(person, lambda s: s.delete_comment(todo, comment.id, expected_version=1))
        check.equal(raised.value.operation, "delete_comment")
        row = world.comment_rows(todo)[0]
        check.equal((row["body"], row["version"], row["deleted_at"]), ("by m1", 1, None))

    def test_admin_can_delete_but_not_edit_others(self, world, todo, comment):
        """tenant_admin は他人のコメントを削除できるが、編集は 403 edit_comment(同じ本文でも 403)。"""
        for body in ("tampered", "by m1"):
            with pytest.raises(TodoPermissionDeniedError) as raised:
                world.comments_call(world.admin, lambda s, body=body: s.update_comment(todo, comment.id, expected_version=1, body=body))
            check.equal(raised.value.operation, "edit_comment", body)
        world.comments_call(world.admin, lambda s: s.delete_comment(todo, comment.id, expected_version=1))
        row = world.comment_rows(todo)[0]
        check.equal((row["body"], row["version"]), ("by m1", 2))
        check.is_not_none(row["deleted_at"])

    def test_admin_can_edit_own_comment(self, world, todo):
        """tenant_admin も自分のコメントは編集できる。"""
        mine = post(world, world.admin, todo, "admin says")
        edited = world.comments_call(world.admin, lambda s: s.update_comment(todo, mine.id, expected_version=1, body="admin edited"))
        check.equal(edited.body, "admin edited")

    def test_same_body_edit_by_non_author_is_still_403(self, world, todo, comment):
        """同じ本文での編集でも、投稿者以外は 403(権限を先に確認する)。何も記録しない。"""
        audits_before = world.todo_audits(todo)
        with pytest.raises(TodoPermissionDeniedError):
            world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="by m1"))
        check.equal(world.todo_audits(todo), audits_before)

    def test_view_permissions_reflect_the_viewer(self, world, todo):
        """一覧の各コメントの permissions は閲覧者ごと: 投稿者 = 編集・削除可、管理者 = 削除のみ、他の member = 不可。"""
        comment = post(world, world.m1, todo)
        got = {
            who: world.comments_call(world.people[who], lambda s: s.list_comments(todo)).items[0].permissions
            for who in ("m1", "admin", "creator")
        }
        check.equal({who: (p.can_edit, p.can_delete) for who, p in got.items()}, {"m1": (True, True), "admin": (False, True), "creator": (False, False)})
        check.equal(comment.permissions.can_edit, True)

    def test_failed_operations_leave_no_trace(self, world, todo, comment):
        """403 で拒否された操作は、監査ログも版の変更も残さない(ロールバック)。"""
        audits_before = world.todo_audits(todo)
        with pytest.raises(TodoPermissionDeniedError):
            world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=1))
        check.equal(world.todo_audits(todo), audits_before)
        check.equal([a["action"] for a in audits_before], ["todo.comment_create"])


class TestOptimisticLock:
    """コメントの版(412 todo_comment_version_conflict。ToDo 本体の版とは別)。"""

    def test_stale_version_is_rejected_for_edit_and_delete(self, world, todo):
        """編集・削除とも、版が合わなければ TodoCommentVersionConflictError(期待・実際の版つき)。コメントは変わらない。"""
        comment = post(world, world.creator, todo)
        world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="v2"))
        with pytest.raises(TodoCommentVersionConflictError) as raised:
            world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="stale"))
        check.equal((raised.value.code, raised.value.resource_id, raised.value.expected_version, raised.value.actual_version), ("todo_comment_version_conflict", comment.id, 1, 2))
        with pytest.raises(TodoCommentVersionConflictError):
            world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=1))
        with pytest.raises(TodoCommentVersionConflictError):
            world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=3))
        row = world.comment_rows(todo)[0]
        check.equal((row["body"], row["version"], row["deleted_at"]), ("v2", 2, None))

    def test_todo_version_is_not_the_comment_version(self, world, todo):
        """ToDo 本体の版(例: 3)と、コメントの版(1)は別。ToDo の版を渡しても通らない。"""
        world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, title="t2"))
        world.call(world.creator, lambda s: s.update_todo(todo, expected_version=2, title="t3"))
        comment = post(world, world.creator, todo)
        with pytest.raises(TodoCommentVersionConflictError):
            world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=3, body="x"))
        check.equal(world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="x")).version, 2)

    def test_concurrent_edits_with_same_version_only_one_wins(self, world, todo):
        """同じ版を期待した 2 つの編集が同時に走っても、1 つだけ成功し、もう 1 つは 412(行ロックで直列化)。"""
        comment = post(world, world.creator, todo)
        barrier = threading.Barrier(2)

        def edit(body):
            barrier.wait()
            try:
                return world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body=body))
            except TodoCommentVersionConflictError as exc:
                return exc

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(edit, ["first", "second"]))
        check.equal(sorted(type(r).__name__ for r in results), ["TodoCommentVersionConflictError", "TodoCommentView"])
        row = world.comment_rows(todo)[0]
        check.equal(row["version"], 2)
        check.is_in(row["body"], ["first", "second"])


class TestOrderOfChecks:
    """変更系の判定の順序: 422 → 404 todo → 404 comment → 412 → 403(ToDoApp.md §9.3)。"""

    @pytest.fixture
    def comment(self, world, todo):
        return post(world, world.m1, todo, "by m1")

    def test_validation_beats_missing_todo(self, world):
        """本文が不正なら、ToDo が存在しなくても 422(入力の形式が先)。"""
        with pytest.raises(TodoValidationError):
            world.comments_call(world.admin, lambda s: s.create_comment(uuid.uuid4(), body=""))
        with pytest.raises(TodoValidationError):
            world.comments_call(world.admin, lambda s: s.update_comment(uuid.uuid4(), uuid.uuid4(), expected_version=1, body=" "))

    def test_missing_todo_beats_missing_comment(self, world, private_todo):
        """閲覧できない ToDo では、コメント ID が存在しなくても todo_not_found(コメントの存在以前に ToDo を明かさない)。"""
        with pytest.raises(TodoNotFoundError):
            world.comments_call(world.outsider, lambda s: s.update_comment(private_todo, uuid.uuid4(), expected_version=1, body="x"))

    def test_missing_comment_beats_version_and_permission(self, world, todo):
        """コメントが無ければ、版が違っても権限が無くても 404 todo_comment_not_found。"""
        with pytest.raises(TodoCommentNotFoundError):
            world.comments_call(world.outsider, lambda s: s.delete_comment(todo, uuid.uuid4(), expected_version=99))

    def test_version_beats_permission(self, world, todo, comment):
        """版が古い非投稿者は、403 ではなく 412(版 → 権限の順)。版が合えば 403。"""
        with pytest.raises(TodoCommentVersionConflictError):
            world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=9, body="x"))
        with pytest.raises(TodoCommentVersionConflictError):
            world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=9))
        with pytest.raises(TodoPermissionDeniedError):
            world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=1))

    def test_validation_beats_version_and_permission(self, world, todo, comment):
        """本文が不正な編集は、版が違っても権限が無くても 422。"""
        with pytest.raises(TodoValidationError):
            world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=9, body=""))


class TestEditSemantics:
    """編集(AP-CMT-03): version +1、edited_at の設定、同じ本文は何もしない。"""

    def test_edit_sets_edited_at_and_bumps_version(self, world, todo):
        """本文を変えると version +1、edited_at が設定される(「編集済み」)。投稿日時は変わらない。"""
        comment = post(world, world.creator, todo, "before")
        before = datetime_now()
        edited = world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="  after  "))
        check.equal((edited.body, edited.version), ("after", 2))
        check.is_true(edited.edited_at is not None and edited.edited_at >= before)
        check.equal(edited.created_at, comment.created_at)
        row = world.comment_rows(todo)[0]
        check.equal((row["body"], row["version"], row["edited_at"] is not None), ("after", 2, True))

    def test_same_body_changes_nothing(self, world, todo):
        """同じ本文(前後の空白を除いて同一)での編集は何もしない: version / edited_at / updated_at を変えず、監査ログも残さない。"""
        comment = post(world, world.creator, todo, "same")
        before = world.comment_rows(todo)[0]
        audits_before = len(world.todo_audits(todo))
        again = world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="  same "))
        check.equal((again.version, again.edited_at, again.body), (1, None, "same"))
        check.equal(world.comment_rows(todo)[0], before)
        check.equal(len(world.todo_audits(todo)), audits_before)

    def test_same_body_with_stale_version_is_still_412(self, world, todo):
        """同じ本文でも、版が違えば 412(版の確認は本文の比較より先)。"""
        comment = post(world, world.creator, todo, "same")
        with pytest.raises(TodoCommentVersionConflictError):
            world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=5, body="same"))

    def test_edit_validation(self, world, todo):
        """編集の本文も投稿と同じ検証(空・4,000 文字超・制御文字は TodoValidationError)。"""
        comment = post(world, world.creator, todo, "ok")
        for body, reason in (("", "required"), ("x" * 4001, "too_long"), ("a\x00", "format")):
            with pytest.raises(TodoValidationError) as raised:
                world.comments_call(world.creator, lambda s, body=body: s.update_comment(todo, comment.id, expected_version=1, body=body))
            check.equal((raised.value.field, raised.value.reason), ("body", reason))


class TestList:
    """一覧(AP-CMT-02 / 05、§10 #19): 古い順、カーソル、削除済みを除く。"""

    def test_oldest_first_with_id_tiebreak(self, world, todo):
        """投稿が古い順に並ぶ。投稿日時が同じなら id の昇順。"""
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        late = world.factory.comment(world.ctx, todo, world.creator, body="late", created_at=base + dt.timedelta(hours=2))
        early = world.factory.comment(world.ctx, todo, world.creator, body="early", created_at=base)
        tie_ids = sorted(world.factory.comment(world.ctx, todo, world.creator, body=f"tie{i}", created_at=base + dt.timedelta(hours=1)) for i in range(3))
        page = world.comments_call(world.admin, lambda s: s.list_comments(todo))
        check.equal([c.id for c in page.items], [early, *tie_ids, late])
        check.is_none(page.next_after)

    def test_cursor_paging_returns_everything_once(self, world, todo):
        """limit 2 でカーソルをたどると、全 5 件が重複・欠落なく古い順に出る。最後のページの next_after は None。"""
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        ids = [world.factory.comment(world.ctx, todo, world.creator, body=f"c{i}", created_at=base + dt.timedelta(minutes=i)) for i in range(5)]
        seen, after, pages = [], None, 0
        while True:
            page = world.comments_call(world.admin, lambda s, after=after: s.list_comments(todo, limit=2, after=after))
            seen += [c.id for c in page.items]
            pages += 1
            if page.next_after is None:
                break
            after = page.next_after
        check.equal((seen, pages), (ids, 3))

    def test_exact_page_boundary_has_no_next(self, world, todo):
        """件数がちょうど limit のとき、next_after は None(次のページは無い)。limit + 1 件なら next_after がある。"""
        for i in range(3):
            world.factory.comment(world.ctx, todo, world.creator, body=f"c{i}")
        check.is_none(world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=3)).next_after)
        check.is_not_none(world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=2)).next_after)

    def test_cursor_stays_valid_when_a_comment_is_added_or_deleted(self, world, todo):
        """カーソルの後に別の投稿・削除があっても、続きは起点より後の生きているコメントだけ(欠落・重複なし)。"""
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        ids = [world.factory.comment(world.ctx, todo, world.creator, body=f"c{i}", created_at=base + dt.timedelta(minutes=i)) for i in range(4)]
        first = world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=2))
        world.comments_call(world.creator, lambda s: s.delete_comment(todo, ids[2], expected_version=1))
        newest = post(world, world.creator, todo, "newest").id
        rest = world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=10, after=first.next_after))
        check.equal([c.id for c in rest.items], [ids[3], newest])

    def test_cursor_accepts_iso_string_datetime(self, world, todo):
        """起点の日時は ISO 8601(タイムゾーン付き)の文字列でも受け付ける。"""
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        ids = [world.factory.comment(world.ctx, todo, world.creator, created_at=base + dt.timedelta(minutes=i)) for i in range(3)]
        page = world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=10, after=((base + dt.timedelta(minutes=0)).isoformat(), str(ids[0]))))
        check.equal([c.id for c in page.items], ids[1:])

    @pytest.mark.parametrize(
        "after",
        ["x", (1,), (1, 2, 3), (dt.datetime(2026, 1, 1), uuid.uuid4()), ("2026-01-01T00:00:00", uuid.uuid4()), ("not-a-date", uuid.uuid4()), (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "not-a-uuid")],
    )
    def test_invalid_cursor_is_rejected(self, world, todo, after):
        """形式が不正な起点(要素数・日時にタイムゾーンが無い・UUID でない)は TodoValidationError(field = cursor)。"""
        with pytest.raises(TodoValidationError) as raised:
            world.comments_call(world.admin, lambda s: s.list_comments(todo, after=after))
        check.equal((raised.value.field, raised.value.reason), ("cursor", "format"))

    def test_deleted_comments_are_excluded(self, world, todo):
        """論理削除したコメントは一覧に出ない(行は残る)。"""
        keep = post(world, world.creator, todo, "keep")
        gone = post(world, world.creator, todo, "gone")
        world.comments_call(world.creator, lambda s: s.delete_comment(todo, gone.id, expected_version=1))
        check.equal([c.id for c in world.comments_call(world.admin, lambda s: s.list_comments(todo)).items], [keep.id])
        check.equal(len(world.comment_rows(todo)), 2)

    def test_limit_is_clamped(self, world, todo):
        """limit は 1〜200 に補正される(0 や負数でも最低 1 件)。"""
        for i in range(3):
            world.factory.comment(world.ctx, todo, world.creator, body=f"c{i}")
        check.equal(len(world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=0)).items), 1)
        check.equal(len(world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=-5)).items), 1)

    def test_only_this_todos_comments(self, world, todo):
        """別の ToDo のコメントは混ざらない。"""
        other = world.factory.add(world.ctx, world.creator, visibility="tenant")
        world.factory.comment(world.ctx, other, world.creator, body="other")
        mine = post(world, world.creator, todo, "mine")
        check.equal([c.id for c in world.comments_call(world.admin, lambda s: s.list_comments(todo)).items], [mine.id])

    def test_edited_flag_is_listed(self, world, todo):
        """編集したコメントは edited_at が付いて一覧に出る。"""
        comment = post(world, world.creator, todo, "a")
        world.comments_call(world.creator, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="b"))
        item = world.comments_call(world.admin, lambda s: s.list_comments(todo)).items[0]
        check.equal((item.body, item.version, item.edited_at is not None), ("b", 2, True))

    def test_list_uses_a_single_query_for_comments_and_authors(self, world, todo):
        """投稿者の表示名は結合して取得する(コメントの件数に依らず、ToDo の取得 + コメントと投稿者の 1 クエリ)。"""
        from sqlalchemy import event

        people = [world.creator, world.assignee, world.m1, world.m2, world.outsider]
        for person in people:
            for i in range(3):
                post(world, person, todo, f"{person.name} {i}")
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if "set_config" not in statement.lower():
                statements.append(statement)

        event.listen(world.ap_db.runtime, "before_cursor_execute", record)
        try:
            page = world.comments_call(world.admin, lambda s: s.list_comments(todo, limit=100))
        finally:
            event.remove(world.ap_db.runtime, "before_cursor_execute", record)
        check.equal(len(page.items), 15)
        check.equal(len(statements), 2, "\n".join(statements))
        check.equal({c.author.display_name for c in page.items}, {p.name for p in people})


class TestDisabledAuthor:
    """投稿者が無効化されてもコメントは残る(AP-CMT-07)。"""

    def test_comment_of_deactivated_author_is_still_listed_with_flag(self, world, todo):
        """無効化されたユーザーのコメントも一覧に出て、author.is_active が False(画面で「無効」と表示する)。"""
        world.factory.comment(world.ctx, todo, world.inactive, body="from inactive")
        alive = post(world, world.creator, todo, "alive")
        items = world.comments_call(world.admin, lambda s: s.list_comments(todo)).items
        got = {c.body: (c.author.id, c.author.is_active, c.author.display_name) for c in items}
        check.equal(got["from inactive"], (world.inactive.id, False, world.inactive.name))
        check.equal(got["alive"], (alive.author.id, True, world.creator.name))

    def test_deactivating_the_author_after_posting_keeps_the_comment(self, world, todo):
        """投稿後に投稿者が無効化されても、コメントは残り is_active が False に変わる。管理者はそのコメントを削除できる。"""
        comment = post(world, world.m1, todo, "posted before")
        from main_app.models import TUser

        with world.ap_db.session(world.ctx) as session:
            user = session.get(TUser, world.m1.id)
            user.is_active = False
            session.commit()
        item = world.comments_call(world.admin, lambda s: s.list_comments(todo)).items[0]
        check.equal((item.id, item.author.is_active), (comment.id, False))
        world.comments_call(world.admin, lambda s: s.delete_comment(todo, comment.id, expected_version=1))


class TestAuditAndSideEffects:
    """監査ログ(本文を残さない)・アクティビティを増やさない・ToDo 本体の版を変えない(AP-CMT-08、AP-CHK-08、§10 #16)。"""

    def test_audit_actions_and_payloads_without_body(self, world, todo):
        """投稿・編集・削除の監査ログ(todo.comment_create / update / delete)が target_type = todo・target_id = ToDo ID で残り、payload に本文が無い。"""
        comment = post(world, world.m1, todo, BODY)
        world.comments_call(world.m1, lambda s: s.update_comment(todo, comment.id, expected_version=1, body=BODY + "-EDITED"))
        world.comments_call(world.admin, lambda s: s.delete_comment(todo, comment.id, expected_version=2))
        audits = world.todo_audits(todo)
        check.equal([a["action"] for a in audits], ["todo.comment_create", "todo.comment_update", "todo.comment_delete"])
        check.equal({(a["target_type"], a["target_id"]) for a in audits}, {("todo", str(todo))})
        check.equal([a["actor_id"] for a in audits], [world.m1.id, world.m1.id, world.admin.id])
        create, update, delete = (a["payload"] for a in audits)
        check.equal(create, {"comment_id": str(comment.id), "body_length": len(BODY)})
        check.equal(update, {"comment_id": str(comment.id), "body_length": {"before": len(BODY), "after": len(BODY) + 7}, "version": {"before": 1, "after": 2}})
        check.equal(delete, {"comment_id": str(comment.id), "author_id": str(world.m1.id), "body_length": len(BODY) + 7, "version": {"before": 2, "after": 3}})
        check.is_not_in("SECRET", repr(audits))

    def test_body_appears_nowhere_except_the_comment_row(self, world, todo):
        """本文は監査ログにもアクティビティにも残らない(コメントの行だけ)。"""
        post(world, world.creator, todo, BODY)
        check.is_not_in(BODY, repr(world.ap_db.audits(world.ctx)))
        check.is_not_in(BODY, repr(world.activities(todo)))

    def test_activities_do_not_grow_and_todo_is_untouched(self, world, todo):
        """投稿・編集・削除でアクティビティは増えず、ToDo 本体の version / updated_at / updated_by も変わらない(ETag を変えない)。"""
        before_todo, before_activities = world.todo(todo), world.activities(todo)
        comment = post(world, world.m1, todo, "one")
        world.comments_call(world.m1, lambda s: s.update_comment(todo, comment.id, expected_version=1, body="two"))
        world.comments_call(world.admin, lambda s: s.delete_comment(todo, comment.id, expected_version=2))
        post(world, world.creator, todo, "three")
        after = world.todo(todo)
        check.equal((after["version"], after["updated_at"], after["updated_by"]), (before_todo["version"], before_todo["updated_at"], before_todo["updated_by"]))
        check.equal(world.activities(todo), before_activities)

    def test_todo_edit_with_stale_etag_is_not_caused_by_comments(self, world, todo):
        """コメントの操作の後でも、ToDo 本体の版(If-Match)はそのまま使える(本体の編集と衝突しない)。"""
        post(world, world.m1, todo, "x")
        view = world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, title="renamed"))
        check.equal(view.version, 2)

    def test_comment_does_not_affect_updated_at_sort(self, world):
        """更新日時順の並びにコメントは反映されない(§10 #16)。コメントを付けた古い ToDo は、更新日時順で新しい ToDo の後ろのまま。"""
        old = world.factory.add(world.ctx, world.creator, title="old", visibility="tenant", created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        new = world.factory.add(world.ctx, world.creator, title="new", visibility="tenant", created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))
        post(world, world.creator, old, "bump?")
        page = world.call(world.admin, lambda s: s.list_todos(sort="-updated_at"))
        check.equal([t.id for t in page.items], [new, old])


class TestDelete:
    """削除(AP-CMT-05): 論理削除。"""

    def test_delete_is_logical_and_bumps_version(self, world, todo):
        """deleted_at が設定され version +1。本文は残る。その後の一覧には出ない。"""
        comment = post(world, world.creator, todo, "bye")
        result = world.comments_call(world.creator, lambda s: s.delete_comment(todo, comment.id, expected_version=1))
        check.is_none(result)
        row = world.comment_rows(todo)[0]
        check.equal((row["body"], row["version"], row["deleted_at"] is not None), ("bye", 2, True))
        check.equal(world.comments_call(world.creator, lambda s: s.list_comments(todo)).items, [])
