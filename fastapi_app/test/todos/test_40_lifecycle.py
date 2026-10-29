# -*- coding: utf-8 -*-
"""ToDo の作成・更新・削除(楽観ロック・論理削除)・公開先組織・クロステナントのテスト(サービス層。実サービス + 実 DB の RLS)。"""
import datetime as dt
import uuid

import pytest
import pytest_check as check

from main_app.models.todo import TODO_DESCRIPTION_MAX_LENGTH, TODO_TITLE_MAX_LENGTH
from main_app.services.errors import InvalidTodoOrganizationsError, TodoNotFoundError, TodoPermissionDeniedError, TodoValidationError, TodoVersionConflictError


class TestCreate:
    """作成(AP-TODO-01..04、AP-VIS-01 / 07)。"""

    def test_defaults(self, world):
        """既定値: status=open、priority=medium、visibility=private、version=1、作成者=更新者=操作者。説明・期限は無し。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="  Buy milk  "))
        check.equal((view.title, view.status.value, view.priority.value, view.visibility.value, view.effective_visibility.value, view.version), ("Buy milk", "open", "medium", "private", "private", 1))
        check.equal((view.created_by, view.updated_by, view.description, view.due_date, view.assignees, view.organizations), (world.creator.id, world.creator.id, None, None, (), ()))
        row = world.todo(view.id)
        check.equal((row["tenant_id"], row["deleted_at"], row["id"].version), (world.ctx.tenant_id, None, 7))

    def test_all_fields(self, world):
        """全項目を指定して作成できる(担当者・公開先組織つき)。詳細には権限(作成者は全操作)が入る。"""
        view = world.call(
            world.creator,
            lambda s: s.create_todo(
                title="T", description="line1\nline2\ttab", due_date=dt.date(2031, 2, 3), priority="low", status="in_progress", visibility="organization",
                organization_ids=[world.o1, world.o2], assignee_ids=[world.assignee.id, world.m1.id],
            ),
        )
        check.equal((view.description, view.due_date, view.priority.value, view.status.value), ("line1\nline2\ttab", dt.date(2031, 2, 3), "low", "in_progress"))
        check.equal({o.id for o in view.organizations}, {world.o1, world.o2})
        check.equal({a.user_id for a in view.assignees}, {world.assignee.id, world.m1.id})
        check.equal({a.assigned_by for a in view.assignees}, {world.creator.id})
        check.is_true(all((view.permissions.can_edit_fields, view.permissions.can_delete, view.permissions.can_change_visibility)))

    @pytest.mark.parametrize(
        ("kwargs", "field", "reason"),
        [
            ({"title": ""}, "title", "required"),
            ({"title": "   "}, "title", "required"),
            ({"title": None}, "title", "required"),
            ({"title": "x" * (TODO_TITLE_MAX_LENGTH + 1)}, "title", "too_long"),
            ({"title": "a\nb"}, "title", "format"),
            ({"title": "a\x00b"}, "title", "format"),
            ({"title": "t", "description": "x" * (TODO_DESCRIPTION_MAX_LENGTH + 1)}, "description", "too_long"),
            ({"title": "t", "description": "a\x00b"}, "description", "format"),
            ({"title": "t", "description": 5}, "description", "type"),
            ({"title": "t", "due_date": dt.datetime(2030, 1, 1, tzinfo=dt.UTC)}, "due_date", "type"),
            ({"title": "t", "due_date": "2030-01-01"}, "due_date", "type"),
            ({"title": "t", "priority": "urgent"}, "priority", "unsupported"),
            ({"title": "t", "status": "blocked"}, "status", "unsupported"),
            ({"title": "t", "visibility": "public"}, "visibility", "unsupported"),
            ({"title": "t", "visibility": "organization"}, "organization_ids", "required"),
            ({"title": "t", "visibility": "private", "organization_ids": [uuid.uuid4()]}, "organization_ids", "not_allowed"),
            ({"title": "t", "organization_ids": "x"}, "organization_ids", "type"),
            ({"title": "t", "organization_ids": ["x"]}, "organization_ids", "format"),
            ({"title": "t", "assignee_ids": None}, "assignee_ids", "type"),
        ],
    )
    def test_validation(self, world, kwargs, field, reason):
        """不正な入力は TodoValidationError(項目と理由付き)で、何も作らない。"""
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.create_todo(**kwargs))
        check.equal((caught.value.field, caught.value.reason, caught.value.code), (field, reason, "invalid_todo_input"))
        check.equal(world.ap_db.rows(world.ctx, "SELECT id FROM t_todo"), [])

    def test_boundaries_are_accepted(self, world):
        """上限ちょうど(タイトル 200 文字、説明 10,000 文字、公開先組織 100 件の指定は別)は作れる。空文字の説明は None にする。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="x" * TODO_TITLE_MAX_LENGTH, description="y" * TODO_DESCRIPTION_MAX_LENGTH))
        check.equal((len(view.title), len(view.description)), (TODO_TITLE_MAX_LENGTH, TODO_DESCRIPTION_MAX_LENGTH))
        check.is_none(world.call(world.creator, lambda s: s.create_todo(title="empty", description="")).description)

    def test_organizations_must_exist_and_be_active(self, world):
        """公開先の組織が存在しない・論理削除済み・他テナントのとき InvalidTodoOrganizationsError(organization_ids 付き)。ToDo は作られない。"""
        foreign = world.ap_db.add_org(world.ap_db.tenant(), "Foreign Org")
        ghost = uuid.uuid4()
        for bad in (ghost, world.o3, foreign.id):
            with pytest.raises(InvalidTodoOrganizationsError) as caught:
                world.call(world.creator, lambda s, bad=bad: s.create_todo(title="x", visibility="organization", organization_ids=[world.o1, bad]))
            check.equal((caught.value.organization_ids, caught.value.code, caught.value.reason), ((bad,), "invalid_todo_organizations", "not_found"))
        check.equal(world.ap_db.rows(world.ctx, "SELECT id FROM t_todo"), [])

    def test_too_many_organizations(self, world):
        """公開先組織は 100 まで(101 件は TodoValidationError too_many)。"""
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.create_todo(title="x", visibility="organization", organization_ids=[uuid.uuid4() for _ in range(101)]))
        check.equal((caught.value.field, caught.value.reason), ("organization_ids", "too_many"))

    def test_audit_snapshot_has_no_description(self, world):
        """作成の監査ログ(todo.create)に説明の本文は含まれず、タイトル等の値は含まれる。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="audited", description="body text"))
        payload = world.todo_audits(view.id)[0]["payload"]
        check.is_not_in("description", payload)
        check.equal(payload["title"], "audited")


class TestUpdate:
    """部分更新(PATCH)。"""

    def test_update_fields_bumps_version_and_updated_by(self, world):
        """項目を更新すると version +1、updated_by=操作者、updated_at が進む。値が変わらない項目はそのまま。"""
        todo_id = world.factory.add(world.ctx, world.creator, title="old", description="d", priority="low", due_date=dt.date(2030, 1, 1))
        before = world.todo(todo_id)
        view = world.call(world.admin, lambda s: s.update_todo(todo_id, expected_version=1, title="  new  ", priority="high", due_date=dt.date(2031, 1, 1)))
        row = world.todo(todo_id)
        check.equal((view.title, view.priority.value, view.due_date, view.description, view.version), ("new", "high", dt.date(2031, 1, 1), "d", 2))
        check.equal((row["updated_by"], row["created_by"], row["version"]), (world.admin.id, world.creator.id, 2))
        check.greater_equal(row["updated_at"], before["updated_at"])

    def test_description_and_due_date_can_be_cleared(self, world):
        """description と due_date は None で消せる(description は空文字でも消える)。他の項目の None は 422(required)。"""
        todo_id = world.factory.add(world.ctx, world.creator, description="d", due_date=dt.date(2030, 1, 1))
        view = world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, description=None, due_date=None))
        check.equal((view.description, view.due_date, view.version), (None, None, 2))
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=2, description="again"))
        check.is_none(world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=3, description="")).description)

    @pytest.mark.parametrize(
        ("kwargs", "field", "reason"),
        [
            ({"title": "x" * 201}, "title", "too_long"),
            ({"title": "a\tb"}, "title", "format"),
            ({"priority": "urgent"}, "priority", "unsupported"),
            ({"status": "blocked"}, "status", "unsupported"),
            ({"visibility": "public"}, "visibility", "unsupported"),
            ({"due_date": dt.datetime(2030, 1, 1, tzinfo=dt.UTC)}, "due_date", "type"),
            ({"organization_ids": "x"}, "organization_ids", "type"),
        ],
    )
    def test_validation(self, world, kwargs, field, reason):
        """不正な入力は TodoValidationError で、何も変えない。"""
        todo_id = world.factory.add(world.ctx, world.creator)
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, **kwargs))
        check.equal((caught.value.field, caught.value.reason), (field, reason))
        check.equal(world.todo(todo_id)["version"], 1)

    def test_sequential_updates_require_the_new_version(self, world):
        """更新後の版でなければ次の更新は TodoVersionConflictError。連続して更新できる。"""
        todo_id = world.factory.add(world.ctx, world.creator)
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="a"))
        with pytest.raises(TodoVersionConflictError):
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="b"))
        check.equal(world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=2, title="b")).version, 3)

    def test_concurrent_updates_only_one_wins(self, world):
        """同じ版の同時更新は行ロックで直列化され、片方だけ成功する(更新の消失なし)。"""
        import threading
        from concurrent.futures import ThreadPoolExecutor

        todo_id = world.factory.add(world.ctx, world.creator)
        barrier = threading.Barrier(2)

        def attempt(title):
            barrier.wait(timeout=10)
            try:
                world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title=title))
            except TodoVersionConflictError:
                return "conflict"
            return "ok"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(attempt, ["one", "two"]))
        check.equal(outcomes, ["conflict", "ok"])
        check.equal(world.todo(todo_id)["version"], 2)

    def test_concurrent_status_change_and_assignee_change_serialize(self, world):
        """ステータス変更と担当者変更が同じ版で同時に来ても、片方だけ成功する(版は 1 つしか進まない)。"""
        import threading
        from concurrent.futures import ThreadPoolExecutor

        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant")
        barrier = threading.Barrier(2)

        def status():
            barrier.wait(timeout=10)
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, status="done"))

        def assignees():
            barrier.wait(timeout=10)
            world.call(world.creator, lambda s: s.set_assignees(todo_id, expected_version=1, user_ids=[world.assignee.id]))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(status), pool.submit(assignees)]
            errors = [f.exception() for f in futures]
        check.equal(sorted(type(e).__name__ if e else "ok" for e in errors), ["TodoVersionConflictError", "ok"])
        check.equal(world.todo(todo_id)["version"], 2)


class TestVisibilityAndOrganizations:
    """閲覧範囲・公開先組織の変更(AP-VIS-07 / 08、§10 #10)。"""

    def test_switch_to_organization_requires_active_organizations(self, world):
        """organization にするには有効な組織が 1 つ以上必要。空・省略は TodoValidationError(organization_ids / required)。削除済みの組織は新たには指定できない。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private")
        for kwargs in ({"visibility": "organization"}, {"visibility": "organization", "organization_ids": []}):
            with pytest.raises(TodoValidationError) as caught:
                world.call(world.creator, lambda s, kwargs=kwargs: s.update_todo(todo_id, expected_version=1, **kwargs))
            check.equal((caught.value.field, caught.value.reason), ("organization_ids", "required"))
        with pytest.raises(InvalidTodoOrganizationsError) as invalid:
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, visibility="organization", organization_ids=[world.o3]))
        check.equal(invalid.value.organization_ids, (world.o3,))
        check.equal((world.todo(todo_id)["visibility"], world.org_rows(todo_id), world.todo(todo_id)["version"]), ("private", [], 1))

    def test_switch_to_organization_sets_links(self, world):
        """organization にして公開先を設定すると、所属者に見えるようになり、公開先が詳細に出る。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private")
        view = world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, visibility="organization", organization_ids=[world.o1]))
        check.equal(([o.name for o in view.organizations], view.effective_visibility.value), (["Org One"], "organization"))
        check.is_not_none(world.call(world.m1, lambda s: s.get_todo(todo_id)))

    def test_leaving_organization_clears_links(self, world):
        """organization 以外に変えると公開先の行を削除する(再び organization にしても元の公開先は残らない)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1])
        world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, visibility="private"))
        check.equal(world.org_rows(todo_id), [])
        with pytest.raises(TodoValidationError):
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=2, visibility="organization"))

    def test_organization_ids_not_allowed_for_other_visibility(self, world):
        """organization 以外の閲覧範囲で空でない organization_ids を送ると TodoValidationError(not_allowed)。空配列は許される。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant")
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, organization_ids=[world.o1]))
        check.equal((caught.value.field, caught.value.reason), ("organization_ids", "not_allowed"))
        check.equal(world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, organization_ids=[])).version, 1)

    def test_update_without_visibility_change_passes_even_if_all_organizations_deleted(self, world):
        """公開先がすべて削除済みの ToDo でも、閲覧範囲・公開先を変えない更新(タイトル・ステータス)はそのまま通る。effective_visibility は private のまま。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o3], assignees=[world.assignee])
        view = world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, title="still ok"))
        check.equal((view.title, view.visibility.value, view.effective_visibility.value), ("still ok", "organization", "private"))
        view = world.call(world.assignee, lambda s: s.update_todo(todo_id, expected_version=2, status="done", visibility="organization", organization_ids=[world.o3]))
        check.equal(view.status.value, "done")

    def test_deleted_organization_may_stay_in_a_set_with_an_active_one(self, world):
        """既に公開先にある削除済みの組織は、有効な組織と一緒なら指定に残してよい(新たには指定できない)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1, world.o3])
        view = world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, organization_ids=[world.o1, world.o2, world.o3]))
        check.equal({o.id for o in view.organizations}, {world.o1, world.o2})
        check.equal(sorted(world.org_rows(todo_id)), sorted([world.o1, world.o2, world.o3]))
        other = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1])
        with pytest.raises(InvalidTodoOrganizationsError):
            world.call(world.creator, lambda s: s.update_todo(other, expected_version=1, organization_ids=[world.o1, world.o3]))

    def test_replacing_only_deleted_organizations_is_rejected(self, world):
        """公開先を、削除済みの組織だけにする更新は TodoValidationError(required: 有効な組織が 1 つも無い)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1, world.o3])
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, organization_ids=[world.o3]))
        check.equal((caught.value.field, caught.value.reason), ("organization_ids", "required"))

    def test_other_tenant_organization_is_rejected(self, world):
        """他テナントの組織を公開先に指定すると InvalidTodoOrganizationsError(存在しない組織と同じ)。"""
        foreign = world.ap_db.add_org(world.ap_db.tenant(), "Foreign")
        todo_id = world.factory.add(world.ctx, world.creator)
        with pytest.raises(InvalidTodoOrganizationsError):
            world.call(world.creator, lambda s: s.update_todo(todo_id, expected_version=1, visibility="organization", organization_ids=[foreign.id]))

    def test_composite_foreign_key_blocks_foreign_organization_at_db_level(self, world):
        """事前チェックが無くても、複合外部キーで他テナントの組織は公開先の行にできない(DB の多重防御)。"""
        from sqlalchemy.exc import IntegrityError

        from main_app.models import TTodoOrganization

        foreign = world.ap_db.add_org(world.ap_db.tenant(), "Foreign")
        todo_id = world.factory.add(world.ctx, world.creator)
        with world.ap_db.session(world.ctx) as session:
            session.add(TTodoOrganization(tenant_id=world.ctx.tenant_id, todo_id=todo_id, organization_id=foreign.id))
            with pytest.raises(IntegrityError):
                session.commit()


class TestDelete:
    """論理削除と楽観ロック(AP-TODO-05、03 §5)。"""

    def test_soft_delete(self, world):
        """削除は論理削除(deleted_at 設定、版 +1、updated_by=操作者)。担当者・公開先・アクティビティの行は残る。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1], assignees=[world.assignee])
        world.call(world.creator, lambda s: s.delete_todo(todo_id, expected_version=1))
        row = world.todo(todo_id)
        check.is_not_none(row["deleted_at"])
        check.equal((row["version"], row["updated_by"]), (2, world.creator.id))
        check.equal((len(world.assignee_rows(todo_id)), world.org_rows(todo_id)), (1, [world.o1]))

    def test_deleted_todo_is_gone_everywhere(self, world):
        """削除後は、誰にとっても(tenant_admin・作成者を含む)一覧・詳細・アクティビティ・更新・再削除・担当者変更が TodoNotFoundError。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant", title="doomed")
        world.call(world.creator, lambda s: s.delete_todo(todo_id, expected_version=1))
        operations = [
            lambda s: s.get_todo(todo_id),
            lambda s: s.list_activities(todo_id),
            lambda s: s.update_todo(todo_id, expected_version=2, title="x"),
            lambda s: s.delete_todo(todo_id, expected_version=2),
            lambda s: s.set_assignees(todo_id, expected_version=2, user_ids=[]),
        ]
        for person in (world.admin, world.creator, world.assignee, world.m1):
            for operation in operations:
                with pytest.raises(TodoNotFoundError):
                    world.call(person, operation)
            check.is_not_in("doomed", [item.title for item in world.call(person, lambda s: s.list_todos()).items])

    def test_delete_stale_version(self, world):
        """版が違えば TodoVersionConflictError で削除しない。"""
        todo_id = world.factory.add(world.ctx, world.creator)
        with pytest.raises(TodoVersionConflictError):
            world.call(world.creator, lambda s: s.delete_todo(todo_id, expected_version=3))
        check.is_none(world.todo(todo_id)["deleted_at"])

    def test_assignee_cannot_delete(self, world):
        """担当者は削除できない(403 delete)。"""
        todo_id = world.factory.add(world.ctx, world.creator, assignees=[world.assignee])
        with pytest.raises(TodoPermissionDeniedError) as caught:
            world.call(world.assignee, lambda s: s.delete_todo(todo_id, expected_version=1))
        check.equal(caught.value.operation, "delete")

    def test_deletion_changes_metrics_count(self, world, app_cp_agent_engine):
        """削除した ToDo は CP のメトリクス(todo_count)の集計から外れる(論理削除を除く)。"""
        from control_plane_app.repositories.app_tenant_metrics import AppTenantMetricsRepository

        collector = AppTenantMetricsRepository(engine_factory=lambda: app_cp_agent_engine)
        keep = world.factory.add(world.ctx, world.creator)
        gone = world.factory.add(world.ctx, world.creator, status="done")
        check.equal(int(collector.collect_tenant_metrics(world.ctx.tenant_id)["todo_count"]), 2)
        world.call(world.creator, lambda s: s.delete_todo(gone, expected_version=1))
        metrics = collector.collect_tenant_metrics(world.ctx.tenant_id)
        check.equal((int(metrics["todo_count"]), int(metrics["todo_done_count"])), (1, 0))
        del keep


class TestCrossTenant:
    """クロステナント(tenant-isolation §5.1): 実サービス + 実 DB の RLS。"""

    @pytest.fixture
    def other(self, world):
        """別テナントと、その管理者・ToDo(担当者・公開先つき)。"""
        ctx = world.ap_db.tenant()
        admin = world.add_person("b_admin", roles=("tenant_admin",), ctx=ctx)
        member = world.add_person("b_member", ctx=ctx)
        org = world.ap_db.add_org(ctx, "B Org", members=(member.id,))
        todo_id = world.factory.add(ctx, admin, title="b todo", visibility="tenant", orgs=[], assignees=[member])
        org_todo = world.factory.add(ctx, admin, title="b org todo", visibility="organization", orgs=[org.id])
        return ctx, admin, member, org, todo_id, org_todo

    def test_other_tenant_todo_is_not_found_for_every_operation(self, world, other):
        """A のユーザー(tenant_admin を含む)が B の ToDo を ID 指定すると、取得・更新・削除・担当者変更・アクティビティのすべてが TodoNotFoundError。B の ToDo は変わらない。"""
        ctx, _, _, _, todo_id, _ = other
        before = world.todo(todo_id, ctx)
        for person in (world.admin, world.creator):
            operations = [
                lambda s: s.get_todo(todo_id),
                lambda s: s.list_activities(todo_id),
                lambda s: s.update_todo(todo_id, expected_version=1, title="hijack", status="done"),
                lambda s: s.delete_todo(todo_id, expected_version=1),
                lambda s: s.set_assignees(todo_id, expected_version=1, user_ids=[world.creator.id]),
            ]
            for operation in operations:
                with pytest.raises(TodoNotFoundError):
                    world.call(person, operation)
        check.equal(world.todo(todo_id, ctx), before)
        check.equal(world.ap_db.rows(ctx, "SELECT user_id FROM t_todo_assignee WHERE todo_id = :id", id=todo_id).__len__(), 1)
        check.equal(world.ap_db.rows(ctx, "SELECT id FROM t_todo_activity"), [])

    def test_lists_and_counts_are_isolated(self, world, other):
        """一覧(絞り込み・scope・並び替え込み)に B の ToDo は現れず、A の作成・削除は B の一覧に影響しない。"""
        ctx, b_admin, _, _, todo_id, org_todo = other
        a_todo = world.factory.add(world.ctx, world.creator, title="a todo", visibility="tenant")
        for scope in ("all", "mine", "assigned", "shared"):
            for sort in ("due_date", "-priority", "created_at", "-updated_at"):
                titles = {i.title for i in world.call(world.admin, lambda s: s.list_todos(scope=scope, sort=sort)).items}
                check.is_not_in("b todo", titles)
                check.is_not_in("b org todo", titles)
        check.equal({i.title for i in world.call(b_admin, lambda s: s.list_todos(), ctx=ctx).items}, {"b todo", "b org todo"})
        world.call(world.creator, lambda s: s.delete_todo(a_todo, expected_version=1))
        world.call(world.creator, lambda s: s.create_todo(title="another a"))
        check.equal({i.title for i in world.call(b_admin, lambda s: s.list_todos(), ctx=ctx).items}, {"b todo", "b org todo"})
        del todo_id, org_todo

    def test_filters_with_other_tenant_ids_match_nothing(self, world, other):
        """絞り込みに B のユーザー・組織の ID を指定しても、A の一覧は空(B の存在を判別できない)。"""
        _, _, member, org, _, _ = other
        world.factory.add(world.ctx, world.creator, visibility="tenant")
        check.equal(world.call(world.admin, lambda s: s.list_todos(assignee_id=member.id)).items, [])
        check.equal(world.call(world.admin, lambda s: s.list_todos(organization_id=org.id)).items, [])

    def test_cannot_assign_or_publish_to_other_tenant(self, world, other):
        """B のユーザーを担当者に、B の組織を公開先にしようとすると 422 相当(not_found)。作成・更新どちらでも。"""
        _, _, member, org, _, _ = other
        mine = world.factory.add(world.ctx, world.creator)
        with pytest.raises(Exception) as assignee_error:
            world.call(world.creator, lambda s: s.set_assignees(mine, expected_version=1, user_ids=[member.id]))
        check.equal(getattr(assignee_error.value, "reason", None), "not_found")
        with pytest.raises(InvalidTodoOrganizationsError):
            world.call(world.creator, lambda s: s.create_todo(title="x", visibility="organization", organization_ids=[org.id]))
        check.equal(world.assignee_rows(mine), [])

    def test_same_user_id_cannot_cross_tenants(self, world, other):
        """B の ToDo の作成者 ID で A のサービスを動かしても(ID を借用しても)、B の ToDo は見えない(RLS が最終防衛線)。"""
        ctx, b_admin, _, _, todo_id, _ = other
        impostor = type(world.admin)(id=b_admin.id, sub=b_admin.sub, name="impostor", roles=("tenant_admin",))
        with pytest.raises(TodoNotFoundError):
            world.call(impostor, lambda s: s.get_todo(todo_id))
        check.equal(world.call(impostor, lambda s: s.list_todos()).items, [])
