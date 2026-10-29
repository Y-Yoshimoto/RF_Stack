# -*- coding: utf-8 -*-
"""ホームの要約(``TodoService.summarize``。AP-UX-01、ToDoApp.md §9.3 / §10 #21)のテスト。

期待値(オラクル)は仕様から手で数える: 閲覧できる ToDo のうち論理削除・完了を除き、``assigned``(自分が担当)の open / in_progress / overdue(``due_date < today``)/
due_soon(``today <= due_date <= today + due_soon_days``)、``created``(自分が作成)の open / in_progress / overdue。
"""
import datetime as dt

import pytest
import pytest_check as check
from sqlalchemy import event

from main_app.services.errors import TodoValidationError

TODAY = dt.date(2030, 6, 15)


def day(offset: int) -> dt.date:
    return TODAY + dt.timedelta(days=offset)


def summary(world, person, *, ctx=None, **kwargs):
    kwargs.setdefault("today", TODAY)
    return world.call(person, lambda s: s.summarize(**kwargs), ctx=ctx)


def flat(view):
    return (
        (view.assigned.open, view.assigned.in_progress, view.assigned.overdue, view.assigned.due_soon),
        (view.created.open, view.created.in_progress, view.created.overdue),
    )


class TestDueBoundaries:
    """期限の境界: 前日 = 期限切れ、当日・+7 日 = 期限間近、+8 日 = どちらでもない。"""

    @pytest.mark.parametrize(
        ("offset", "overdue", "due_soon"),
        [(-30, 1, 0), (-1, 1, 0), (0, 0, 1), (1, 0, 1), (6, 0, 1), (7, 0, 1), (8, 0, 0), (30, 0, 0)],
    )
    def test_assigned_boundaries_with_default_days(self, world, offset, overdue, due_soon):
        """担当 ToDo の期限が today に対して offset 日: 前日(-1)は期限切れ、当日(0)と +7 日は期限間近、+8 日はどちらでもない(既定 7 日)。open の件数は常に 1。"""
        world.factory.add(world.ctx, world.creator, due_date=day(offset), assignees=[world.assignee])
        view = summary(world, world.assignee)
        check.equal(flat(view)[0], (1, 0, overdue, due_soon))
        check.equal((view.today, view.due_soon_days, view.due_soon_until), (TODAY, 7, day(7)))

    @pytest.mark.parametrize(
        ("days", "offset", "due_soon"),
        [(1, 1, 1), (1, 2, 0), (30, 30, 1), (30, 31, 0), (3, 3, 1), (3, 4, 0)],
    )
    def test_custom_due_soon_days(self, world, days, offset, due_soon):
        """due_soon_days を変えると、終端(today + days)を含み、その翌日は含まない。1 日・30 日が境界値。"""
        world.factory.add(world.ctx, world.creator, due_date=day(offset), assignees=[world.assignee])
        view = summary(world, world.assignee, due_soon_days=days)
        check.equal((flat(view)[0][3], view.due_soon_until, view.due_soon_days), (due_soon, day(days), days))

    def test_no_due_date_is_neither_overdue_nor_due_soon(self, world):
        """期限なしの ToDo は open として数えるが、期限切れにも期限間近にも入らない。"""
        world.factory.add(world.ctx, world.creator, due_date=None, assignees=[world.assignee])
        check.equal(flat(summary(world, world.assignee))[0], (1, 0, 0, 0))

    def test_today_is_the_clients_date_not_the_servers(self, world):
        """today を変えれば分類が変わる(クライアントのローカル日付を受け取る)。同じ ToDo が、today によって期限切れ / 期限間近 / どちらでもない。"""
        world.factory.add(world.ctx, world.creator, due_date=TODAY, assignees=[world.assignee])
        results = [flat(summary(world, world.assignee, today=TODAY + dt.timedelta(days=offset)))[0][2:] for offset in (-8, -7, 0, 1, 365)]
        check.equal(results, [(0, 0), (0, 1), (0, 1), (1, 0), (1, 0)])

    def test_omitted_today_uses_utc_date(self, world):
        """today を省略すると UTC の日付(日付をまたぐ瞬間に備え、前後 1 日を許容)。"""
        before = dt.datetime.now(dt.UTC).date()
        view = world.call(world.assignee, lambda s: s.summarize())
        after = dt.datetime.now(dt.UTC).date()
        check.is_in(view.today, {before, after})
        check.equal(view.due_soon_until, view.today + dt.timedelta(days=7))


class TestCounting:
    """何を数えるか。"""

    @pytest.fixture
    def data(self, world):
        """assignee の視点で数える ToDo を、作成者・担当者・状態・期限を変えて作る。"""
        f, c = world.factory, world.ctx
        me, other = world.assignee, world.creator
        ids = {}
        # 自分が担当(作成者は他人)
        ids["a_open_overdue"] = f.add(c, other, status="open", due_date=day(-2), assignees=[me], visibility="private")
        ids["a_wip_overdue"] = f.add(c, other, status="in_progress", due_date=day(-1), assignees=[me])
        ids["a_open_soon"] = f.add(c, other, status="open", due_date=day(0), assignees=[me, world.m1])
        ids["a_wip_soon"] = f.add(c, other, status="in_progress", due_date=day(7), assignees=[me])
        ids["a_open_far"] = f.add(c, other, status="open", due_date=day(8), assignees=[me])
        ids["a_open_none"] = f.add(c, other, status="open", assignees=[me])
        ids["a_done_overdue"] = f.add(c, other, status="done", due_date=day(-5), assignees=[me])
        ids["a_done_soon"] = f.add(c, other, status="done", due_date=day(2), assignees=[me])
        ids["a_deleted_open"] = f.add(c, other, status="open", due_date=day(-1), assignees=[me], deleted=True)
        # 自分が作成
        ids["c_open_overdue"] = f.add(c, me, status="open", due_date=day(-3))
        ids["c_wip_overdue"] = f.add(c, me, status="in_progress", due_date=day(-1))
        ids["c_open_soon"] = f.add(c, me, status="open", due_date=day(1))
        ids["c_done"] = f.add(c, me, status="done", due_date=day(-9))
        ids["c_deleted"] = f.add(c, me, status="open", due_date=day(-1), deleted=True)
        # 自分が作成し自分が担当(両方に数える)
        ids["both_wip_overdue"] = f.add(c, me, status="in_progress", due_date=day(-4), assignees=[me])
        # 自分は無関係(閲覧できても数えない)
        ids["shared_open_overdue"] = f.add(c, other, status="open", due_date=day(-1), visibility="tenant")
        ids["others_assigned"] = f.add(c, other, status="open", due_date=day(0), assignees=[world.m1], visibility="tenant")
        ids["others_created_by_m1"] = f.add(c, world.m1, status="open", due_date=day(-1), visibility="tenant")
        return ids

    def test_counts_for_assignee(self, world, data):
        """担当 = open 4 + 両方の 0(in_progress は 3)、…を手計算した値と一致する。

        assigned: open = a_open_overdue / a_open_soon / a_open_far / a_open_none = 4、in_progress = a_wip_overdue / a_wip_soon / both = 3、
        overdue = a_open_overdue / a_wip_overdue / both = 3、due_soon = a_open_soon / a_wip_soon = 2。
        created: open = c_open_overdue / c_open_soon = 2、in_progress = c_wip_overdue / both = 2、overdue = c_open_overdue / c_wip_overdue / both = 3。
        """
        check.equal(flat(summary(world, world.assignee)), ((4, 3, 3, 2), (2, 2, 3)))

    def test_done_and_deleted_are_never_counted(self, world, data):
        """完了(done)と論理削除は、期限の状態にかかわらずどの件数にも入らない(上の期待値に含まれない)。さらに ToDo を削除すると件数から外れる。"""
        base = flat(summary(world, world.assignee))
        world.call(world.creator, lambda s: s.delete_todo(data["a_open_overdue"], expected_version=1))
        after = flat(summary(world, world.assignee))
        check.equal(after[0][0] + 1, base[0][0])
        check.equal(after[0][2] + 1, base[0][2])

    def test_changing_status_moves_counts(self, world, data):
        """担当 ToDo を完了にすると件数から外れ、open → in_progress に変えると内訳が移る。"""
        before = flat(summary(world, world.assignee))
        world.call(world.assignee, lambda s: s.update_todo(data["a_open_soon"], expected_version=1, status="done"))
        after = flat(summary(world, world.assignee))
        check.equal((after[0][0], after[0][3]), (before[0][0] - 1, before[0][3] - 1))
        world.call(world.assignee, lambda s: s.update_todo(data["a_open_overdue"], expected_version=1, status="in_progress"))
        moved = flat(summary(world, world.assignee))
        check.equal((moved[0][0], moved[0][1], moved[0][2]), (after[0][0] - 1, after[0][1] + 1, after[0][2]))

    def test_other_people_have_their_own_counts(self, world, data):
        """同じデータでも操作者ごとの値: m1 は a_open_soon を担当(1)・others_assigned を担当(1)・others_created_by_m1 を作成(1)。作成者の creator は担当を持たない。"""
        check.equal(flat(summary(world, world.m1)), ((2, 0, 0, 2), (1, 0, 1)))
        creator_view = flat(summary(world, world.creator))
        check.equal(creator_view[0], (0, 0, 0, 0))

    def test_admin_counts_only_own_assigned_and_created(self, world, data):
        """tenant_admin は全 ToDo を閲覧できるが、要約は自分が担当・作成したものだけ(閲覧できるものを全部は数えない)。"""
        check.equal(flat(summary(world, world.admin)), ((0, 0, 0, 0), (0, 0, 0)))
        world.factory.add(world.ctx, world.creator, status="open", due_date=day(-1), assignees=[world.admin])
        world.factory.add(world.ctx, world.admin, status="in_progress", due_date=day(1))
        check.equal(flat(summary(world, world.admin)), ((1, 0, 1, 0), (0, 1, 0)))

    def test_nobody_else_sees_other_tenants(self, world, data):
        """他テナントの ToDo は数えない: 別テナントに同じ人数分の ToDo があっても、自テナントの値は変わらない。"""
        before = flat(summary(world, world.assignee))
        ctx = world.ap_db.tenant()
        admin = world.add_person("f_admin", roles=("tenant_admin",), ctx=ctx)
        for offset in (-3, 0, 5):
            world.factory.add(ctx, admin, due_date=day(offset), assignees=[admin])
        check.equal(flat(summary(world, world.assignee)), before)
        check.equal(flat(summary(world, admin, ctx=ctx)), ((3, 0, 1, 2), (3, 0, 1)))

    def test_unrelated_todos_are_not_counted_even_if_visible(self, world):
        """tenant 公開でも、自分が作成者でも担当者でもない ToDo は数えない。"""
        world.factory.add(world.ctx, world.creator, due_date=day(-1), visibility="tenant")
        check.equal(flat(summary(world, world.outsider)), ((0, 0, 0, 0), (0, 0, 0)))

    def test_removed_assignee_is_no_longer_counted(self, world):
        """担当者から外れた ToDo は数えなくなる(担当者の全置換の反映)。"""
        todo = world.factory.add(world.ctx, world.creator, due_date=day(0), assignees=[world.assignee])
        check.equal(flat(summary(world, world.assignee))[0], (1, 0, 0, 1))
        world.call(world.creator, lambda s: s.set_assignees(todo, expected_version=1, user_ids=[]))
        check.equal(flat(summary(world, world.assignee))[0], (0, 0, 0, 0))

    def test_empty(self, world):
        """ToDo が無ければ全て 0。"""
        check.equal(flat(summary(world, world.admin)), ((0, 0, 0, 0), (0, 0, 0)))


class TestValidation:
    """入力の検証(TodoValidationError。API では 422)。"""

    @pytest.mark.parametrize("days", [0, -1, 31, 100])
    def test_due_soon_days_out_of_range(self, world, days):
        """due_soon_days は 1〜30。0・31 などの範囲外は field = due_soon_days / reason = out_of_range。"""
        with pytest.raises(TodoValidationError) as raised:
            summary(world, world.admin, due_soon_days=days)
        check.equal((raised.value.code, raised.value.field, raised.value.reason), ("invalid_todo_input", "due_soon_days", "out_of_range"))

    @pytest.mark.parametrize("days", [1, 30])
    def test_due_soon_days_bounds_are_accepted(self, world, days):
        """1 と 30 は受け付ける。"""
        check.equal(summary(world, world.admin, due_soon_days=days).due_soon_days, days)

    @pytest.mark.parametrize("days", ["7", 7.0, True, None])
    def test_due_soon_days_type(self, world, days):
        """due_soon_days が整数でない(文字列・小数・真偽値・None)場合は type。"""
        with pytest.raises(TodoValidationError) as raised:
            summary(world, world.admin, due_soon_days=days)
        check.equal((raised.value.field, raised.value.reason), ("due_soon_days", "type"))

    @pytest.mark.parametrize("today", [dt.datetime(2030, 6, 15, tzinfo=dt.UTC), dt.datetime(2030, 6, 15), "2030-06-15", 20300615])
    def test_today_must_be_a_date(self, world, today):
        """today が日付でない(datetime・文字列・数値)場合は type(datetime は日付として受け付けない)。"""
        with pytest.raises(TodoValidationError) as raised:
            summary(world, world.admin, today=today)
        check.equal((raised.value.field, raised.value.reason), ("today", "type"))

    def test_today_overflow(self, world):
        """today + due_soon_days が日付の上限を超える場合は today / out_of_range。"""
        with pytest.raises(TodoValidationError) as raised:
            summary(world, world.admin, today=dt.date.max, due_soon_days=7)
        check.equal((raised.value.field, raised.value.reason), ("today", "out_of_range"))
        check.equal(summary(world, world.admin, today=dt.date.max - dt.timedelta(days=7)).due_soon_until, dt.date.max)


def test_summary_is_a_single_query(world):
    """要約は SQL 1 本(件数の多さに依存しない。AP-UX-01)。"""
    for offset in range(-3, 10):
        world.factory.add(world.ctx, world.creator, due_date=day(offset), assignees=[world.assignee], status="in_progress" if offset % 2 else "open")
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "set_config" not in statement.lower():
            statements.append(statement)

    event.listen(world.ap_db.runtime, "before_cursor_execute", record)
    try:
        summary(world, world.assignee)
    finally:
        event.remove(world.ap_db.runtime, "before_cursor_execute", record)
    check.equal(len(statements), 1, "\n".join(statements))
    check.is_true("FILTER" in statements[0].upper(), statements[0])
