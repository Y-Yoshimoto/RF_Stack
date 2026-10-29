# -*- coding: utf-8 -*-
"""ToDo 一覧の総件数(``include_total``)と、一覧・詳細に付く値(作成者・更新者・チェックリストの進捗・コメント数)のテスト。

仕様: AP-UX-02 / 03 / 09、ToDoApp.md §9.3(``list_todos`` の ``include_total``: 表示範囲・絞り込みを適用し、カーソルに依存しない SQL 1 本。
``load_todo_counters``: 削除済みコメントを数えない)。総件数の期待値は、同じ条件で全ページを辿った件数(オラクル)と一致することで確認する。
"""
import datetime as dt

import pytest
import pytest_check as check
from sqlalchemy import event

from main_app.services.errors import TodoValidationError


@pytest.fixture
def dataset(world):
    """閲覧範囲・担当者・組織・ステータスを混ぜた ToDo(論理削除を含む)。"""
    f, c = world.factory, world.ctx
    day = dt.date(2030, 6, 10)
    ids = {
        "tenant_open": f.add(c, world.creator, title="Report tenant", visibility="tenant", status="open", priority="high", due_date=day),
        "tenant_done": f.add(c, world.creator, title="Report done", visibility="tenant", status="done", priority="low", due_date=day + dt.timedelta(days=3)),
        "private_assigned": f.add(c, world.creator, title="Private assigned", visibility="private", status="in_progress", assignees=[world.assignee, world.m1]),
        "private_plain": f.add(c, world.creator, title="Private plain", visibility="private"),
        "org1": f.add(c, world.creator, title="Org one report", visibility="organization", orgs=[world.o1], assignees=[world.m2]),
        "org2": f.add(c, world.creator, title="Org two", visibility="organization", orgs=[world.o2]),
        "org_deleted": f.add(c, world.creator, title="Org deleted", visibility="organization", orgs=[world.o3]),
        "m1_own": f.add(c, world.m1, title="M1 own report", visibility="tenant", priority="high"),
        "m1_private": f.add(c, world.m1, title="M1 private", visibility="private", assignees=[world.assignee]),
        "deleted_tenant": f.add(c, world.creator, title="Report deleted", visibility="tenant", deleted=True),
        "deleted_assigned": f.add(c, world.creator, title="Deleted assigned", visibility="private", assignees=[world.m1], deleted=True),
    }
    return ids


def other_tenant_noise(world):
    """別テナントに ToDo を作る(総件数に混ざらないことの確認用)。"""
    ctx = world.ap_db.tenant()
    person = world.add_person("noise", roles=("tenant_admin",), ctx=ctx)
    for index in range(3):
        world.factory.add(ctx, person, title=f"Report noise {index}", visibility="tenant", assignees=[person])
    return ctx, person


def walk_ids(world, person, *, limit=3, **filters):
    """全ページを辿った ToDo の ID(オラクル)。"""
    ids, after = [], None
    for _ in range(100):
        page = world.call(person, lambda s, after=after: s.list_todos(limit=limit, after=after, **filters))
        ids += [t.id for t in page.items]
        if page.next_after is None:
            return ids
        after = page.next_after
    raise AssertionError("ページが終わらない")


PEOPLE = ["admin", "creator", "assignee", "m1", "m2", "outsider", "n3"]
SCOPES = ["all", "mine", "assigned", "shared"]


class TestTotal:
    """``include_total=True`` の総件数。"""

    @pytest.mark.parametrize("who", PEOPLE)
    @pytest.mark.parametrize("scope", SCOPES)
    def test_total_equals_the_number_of_listed_items(self, world, dataset, who, scope):
        """総件数 = 同じ条件で全ページを辿った件数(閲覧範囲 × 表示範囲)。ページサイズ・カーソルには依存しない。"""
        person = world.people[who]
        expected = len(walk_ids(world, person, scope=scope))
        for limit in (1, 2, 50):
            page = world.call(person, lambda s, limit=limit: s.list_todos(scope=scope, limit=limit, include_total=True))
            check.equal(page.total, expected, f"{who}/{scope}/limit={limit}")

    def test_known_totals_for_each_person(self, world, dataset):
        """実際の件数(手計算): 管理者は論理削除を除く全 9 件、作成者は 7 件。"""
        totals = {who: world.call(world.people[who], lambda s: s.list_todos(include_total=True)).total for who in PEOPLE}
        # 閲覧できる ToDo: tenant_open / tenant_done / m1_own は全員、それ以外は作成者・担当者・公開先の組織・管理者
        check.equal(totals["admin"], 9)
        check.equal(totals["creator"], 8, "creator が作成した 7 件 + m1_own(tenant 公開)")
        check.equal(totals["assignee"], 5, "tenant 公開 3 + 担当 2(private_assigned / m1_private)")
        check.equal(totals["m1"], 6, "tenant 公開 3(m1_own を含む)+ private_assigned(担当)+ org1(O1 所属)+ m1_private(作成)")
        check.equal(totals["outsider"], 3)
        check.equal(totals["n3"], 3, "削除済みの組織だけに所属 → 公開先のない organization の ToDo は見えない")

    def test_total_is_the_same_on_every_page(self, world, dataset):
        """カーソルで進んでも総件数は変わらない(最後のページでも全体の件数)。"""
        totals, after = [], None
        while True:
            page = world.call(world.admin, lambda s, after=after: s.list_todos(limit=2, after=after, include_total=True))
            totals.append(page.total)
            if page.next_after is None:
                break
            after = page.next_after
        check.equal(set(totals), {9})
        check.equal(len(totals), 5)

    @pytest.mark.parametrize(
        "filters",
        [
            {"status": "open"},
            {"status": ["open", "in_progress"]},
            {"priority": "high"},
            {"priority": ["low", "high"]},
            {"q": "report"},
            {"q": "REPORT", "status": "done"},
            {"due_before": dt.date(2030, 6, 10)},
            {"due_after": dt.date(2030, 6, 11)},
            {"due_after": dt.date(2030, 6, 10), "due_before": dt.date(2030, 6, 13)},
            {"organization_id": "o1"},
            {"organization_id": "o3"},
            {"assignee_id": "assignee"},
            {"assignee_id": "m1", "status": "in_progress"},
            {"q": "nothing matches this"},
        ],
    )
    @pytest.mark.parametrize("who", ["admin", "m1", "outsider"])
    def test_total_follows_filters(self, world, dataset, filters, who):
        """絞り込み(ステータス・優先度・タイトル・期限・組織・担当者)を適用した件数と一致する。"""
        resolved = dict(filters)
        if "organization_id" in resolved:
            resolved["organization_id"] = world.orgs[resolved["organization_id"]]
        if "assignee_id" in resolved:
            resolved["assignee_id"] = world.people[resolved["assignee_id"]].id
        person = world.people[who]
        expected = len(walk_ids(world, person, **resolved))
        page = world.call(person, lambda s: s.list_todos(limit=2, include_total=True, **resolved))
        check.equal(page.total, expected)

    @pytest.mark.parametrize("scope", SCOPES)
    def test_total_follows_scope_and_filters_together(self, world, dataset, scope):
        """表示範囲と絞り込みの組み合わせでも一致する。"""
        filters = {"scope": scope, "priority": ["high", "medium"], "q": "r"}
        expected = len(walk_ids(world, world.m1, **filters))
        check.equal(world.call(world.m1, lambda s: s.list_todos(include_total=True, **filters)).total, expected)

    def test_total_ignores_sort(self, world, dataset):
        """並び順を変えても総件数は同じ。"""
        totals = {world.call(world.admin, lambda s, sort=sort: s.list_todos(sort=sort, limit=1, include_total=True)).total for sort in ("created_at", "-due_date", "priority", "-updated_at")}
        check.equal(totals, {9})

    def test_total_excludes_deleted_and_other_tenants(self, world, dataset):
        """論理削除済みと他テナントの ToDo は数えない。他テナントの管理者の総件数にも自テナントは混ざらない。"""
        ctx, other_admin = other_tenant_noise(world)
        before = world.call(world.admin, lambda s: s.list_todos(include_total=True)).total
        mine = world.call(world.admin, lambda s: s.list_todos(include_total=True, q="report")).total
        theirs = world.call(other_admin, lambda s: s.list_todos(include_total=True, q="report"), ctx=ctx).total
        check.equal((before, mine, theirs), (9, 4, 3))

    def test_total_after_delete_and_create(self, world, dataset):
        """ToDo を削除すると総件数が 1 減り、作成すると 1 増える。"""
        base = world.call(world.admin, lambda s: s.list_todos(include_total=True)).total
        world.call(world.creator, lambda s: s.delete_todo(dataset["tenant_open"], expected_version=1))
        check.equal(world.call(world.admin, lambda s: s.list_todos(include_total=True)).total, base - 1)
        world.call(world.creator, lambda s: s.create_todo(title="new"))
        check.equal(world.call(world.admin, lambda s: s.list_todos(include_total=True)).total, base)

    def test_total_is_none_unless_requested(self, world, dataset):
        """include_total を指定しない(False)と total は None(総件数は要求したときだけ)。"""
        check.is_none(world.call(world.admin, lambda s: s.list_todos()).total)
        check.is_none(world.call(world.admin, lambda s: s.list_todos(include_total=False)).total)

    def test_empty_result_has_total_zero(self, world):
        """ToDo が 1 件も無くても total は 0(None ではない)。"""
        page = world.call(world.admin, lambda s: s.list_todos(include_total=True))
        check.equal((page.items, page.total, page.next_after), ([], 0, None))

    @pytest.mark.parametrize("value", [1, "true", None, 0])
    def test_include_total_must_be_a_bool(self, world, value):
        """include_total が真偽値でなければ TodoValidationError(field = include_total)。"""
        with pytest.raises(TodoValidationError) as raised:
            world.call(world.admin, lambda s: s.list_todos(include_total=value))
        check.equal((raised.value.field, raised.value.reason), ("include_total", "type"))

    def test_total_costs_exactly_one_extra_query(self, world, dataset):
        """総件数は SQL 1 本の追加(件数の多さに依存しない)。"""

        def count_queries(include_total):
            statements: list[str] = []

            def record(conn, cursor, statement, parameters, context, executemany):
                if "set_config" not in statement.lower():
                    statements.append(statement)

            event.listen(world.ap_db.runtime, "before_cursor_execute", record)
            try:
                world.call(world.m1, lambda s: s.list_todos(limit=3, include_total=include_total))
            finally:
                event.remove(world.ap_db.runtime, "before_cursor_execute", record)
            return statements

        without, with_total = count_queries(False), count_queries(True)
        check.equal(len(with_total), len(without) + 1)
        check.is_true("count(*)" in with_total[-1].lower() and "LIMIT" not in with_total[-1].upper(), with_total[-1])


class TestCreatorAndUpdater:
    """作成者・更新者の表示名(AP-UX-03 / 09)。"""

    def test_creator_and_updater_names(self, world):
        """一覧・詳細に作成者と最終更新者(UserNameView)が入る。作成直後は更新者 = 作成者。他の人が更新すると更新者が変わる。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="t", visibility="tenant"))
        item = world.call(world.admin, lambda s: s.list_todos()).items[0]
        check.equal((item.creator.id, item.creator.display_name, item.creator.is_active), (world.creator.id, world.creator.name, True))
        check.equal((item.updater.id, item.updater.display_name), (world.creator.id, world.creator.name))
        world.call(world.admin, lambda s: s.update_todo(view.id, expected_version=1, title="t2"))
        item = world.call(world.creator, lambda s: s.list_todos()).items[0]
        detail = world.call(world.creator, lambda s: s.get_todo(view.id))
        for entry in (item, detail):
            check.equal((entry.creator.id, entry.updater.id, entry.updater.display_name, entry.updated_by), (world.creator.id, world.admin.id, world.admin.name, world.admin.id))

    def test_inactive_creator_is_flagged(self, world):
        """作成者・更新者が無効化されたユーザーでも ToDo は残り、is_active が False になる(画面では「無効」)。"""
        todo = world.factory.add(world.ctx, world.inactive, title="by inactive", visibility="tenant")
        item = world.call(world.admin, lambda s: s.list_todos()).items[0]
        check.equal((item.id, item.creator.id, item.creator.is_active, item.updater.is_active), (todo, world.inactive.id, False, False))

    def test_names_are_resolved_for_the_whole_page(self, world):
        """複数の作成者の ToDo が並ぶページで、それぞれの作成者の表示名が正しく対応する。"""
        mapping = {}
        for person in (world.creator, world.m1, world.m2, world.admin, world.inactive):
            mapping[world.factory.add(world.ctx, person, title=f"by {person.name}", visibility="tenant")] = person
        items = world.call(world.admin, lambda s: s.list_todos(limit=10)).items
        check.equal({i.id: (i.creator.id, i.creator.display_name) for i in items}, {tid: (p.id, p.name) for tid, p in mapping.items()})


class TestCounters:
    """チェックリストの進捗とコメント数(AP-CHK-06、AP-UX-03)。"""

    def test_zero_when_nothing(self, world):
        """チェックリストもコメントも無い ToDo は 0 / 0、コメント 0。"""
        world.factory.add(world.ctx, world.creator, visibility="tenant")
        item = world.call(world.admin, lambda s: s.list_todos()).items[0]
        check.equal((item.checklist.done_count, item.checklist.total_count, item.comment_count), (0, 0, 0))

    def test_values_per_todo_on_one_page(self, world):
        """ToDo ごとに値が対応する: A = 項目 3(完了 1)・コメント 2、B = 項目 2(完了 2)・コメント 0、C = 項目 0・コメント 1。"""
        f, c = world.factory, world.ctx
        a, b, cc = (f.add(c, world.creator, title=name, visibility="tenant") for name in "ABC")
        f.item(c, a, world.creator, position=0, done_by=world.assignee)
        f.item(c, a, world.creator, position=1)
        f.item(c, a, world.creator, position=2)
        f.item(c, b, world.creator, position=0, done_by=world.creator)
        f.item(c, b, world.creator, position=1, done_by=world.admin)
        f.comment(c, a, world.creator)
        f.comment(c, a, world.m1)
        f.comment(c, cc, world.m2)
        got = {i.id: (i.checklist.done_count, i.checklist.total_count, i.comment_count) for i in world.call(world.admin, lambda s: s.list_todos()).items}
        check.equal(got, {a: (1, 3, 2), b: (2, 2, 0), cc: (0, 0, 1)})

    def test_deleted_comments_are_not_counted(self, world):
        """論理削除したコメントは数えない(コメント数は生きているものだけ)。"""
        todo = world.factory.add(world.ctx, world.creator, visibility="tenant")
        keep = world.factory.comment(world.ctx, todo, world.creator)
        world.factory.comment(world.ctx, todo, world.creator, deleted=True)
        world.factory.comment(world.ctx, todo, world.m1, deleted=True)
        check.equal(world.call(world.admin, lambda s: s.list_todos()).items[0].comment_count, 1)
        world.comments_call(world.creator, lambda s: s.delete_comment(todo, keep, expected_version=1))
        check.equal(world.call(world.admin, lambda s: s.list_todos()).items[0].comment_count, 0)

    def test_counts_follow_service_operations(self, world):
        """サービスで投稿・追加・チェック・削除すると、一覧と詳細の値がそのとおり変わる。"""
        todo = world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.assignee])
        world.comments_call(world.m1, lambda s: s.create_comment(todo, body="hi"))
        view = world.checklist_call(world.creator, lambda s: s.add_item(todo, title="a"))
        view = world.checklist_call(world.creator, lambda s: s.add_item(todo, title="b"))
        world.checklist_call(world.assignee, lambda s: s.update_item(todo, view.items[0].id, expected_version=1, is_done=True))
        for entry in (world.call(world.admin, lambda s: s.list_todos()).items[0], world.call(world.admin, lambda s: s.get_todo(todo))):
            check.equal((entry.checklist.done_count, entry.checklist.total_count, entry.comment_count), (1, 2, 1))
        world.checklist_call(world.creator, lambda s: s.delete_item(todo, view.items[0].id, expected_version=2))
        entry = world.call(world.admin, lambda s: s.get_todo(todo))
        check.equal((entry.checklist.done_count, entry.checklist.total_count), (0, 1))

    def test_other_todos_and_tenants_are_not_mixed(self, world):
        """別の ToDo・他テナントのコメント / 項目の数は混ざらない。"""
        ctx, person = other_tenant_noise(world)
        foreign = world.factory.add(ctx, person, visibility="tenant")
        world.factory.comment(ctx, foreign, person)
        world.factory.item(ctx, foreign, person)
        mine = world.factory.add(world.ctx, world.creator, visibility="tenant")
        world.factory.comment(world.ctx, mine, world.creator)
        entry = world.call(world.admin, lambda s: s.get_todo(mine))
        check.equal((entry.comment_count, entry.checklist.total_count), (1, 0))

    def test_counts_on_a_page_do_not_depend_on_cursor(self, world):
        """ページを分けて辿っても、各 ToDo の値は同じ。"""
        f, c = world.factory, world.ctx
        ids = [f.add(c, world.creator, visibility="tenant", title=f"t{i}") for i in range(5)]
        for index, todo_id in enumerate(ids):
            for position in range(index):
                f.item(c, todo_id, world.creator, position=position)
            for _ in range(index % 3):
                f.comment(c, todo_id, world.creator)
        expected = {todo_id: (0, index, index % 3) for index, todo_id in enumerate(ids)}
        got, after = {}, None
        while True:
            page = world.call(world.admin, lambda s, after=after: s.list_todos(limit=2, after=after))
            got.update({i.id: (i.checklist.done_count, i.checklist.total_count, i.comment_count) for i in page.items})
            if page.next_after is None:
                break
            after = page.next_after
        check.equal(got, expected)

    def test_create_and_update_responses_carry_the_counters(self, world):
        """作成・更新・担当者変更の応答(詳細)にも値が入る(作成直後は 0)。"""
        view = world.call(world.creator, lambda s: s.create_todo(title="x"))
        check.equal((view.checklist.total_count, view.comment_count, view.creator.id, view.updater.id), (0, 0, world.creator.id, world.creator.id))
        world.factory.item(world.ctx, view.id, world.creator)
        world.factory.comment(world.ctx, view.id, world.creator)
        updated = world.call(world.creator, lambda s: s.update_todo(view.id, expected_version=1, title="y"))
        check.equal((updated.checklist.total_count, updated.comment_count), (1, 1))
        assigned = world.call(world.creator, lambda s: s.set_assignees(view.id, expected_version=2, user_ids=[world.assignee.id]))
        check.equal((assigned.checklist.total_count, assigned.comment_count), (1, 1))

    def test_pagination_order_unaffected_by_counters(self, world):
        """コメント・項目を足しても一覧の並び(作成日時順)は変わらない。"""
        f, c = world.factory, world.ctx
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        ids = [f.add(c, world.creator, visibility="tenant", created_at=base + dt.timedelta(minutes=i)) for i in range(3)]
        f.comment(c, ids[0], world.creator)
        f.item(c, ids[0], world.creator)
        check.equal([i.id for i in world.call(world.admin, lambda s: s.list_todos()).items], list(reversed(ids)))

