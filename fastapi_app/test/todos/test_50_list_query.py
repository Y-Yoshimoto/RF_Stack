# -*- coding: utf-8 -*-
"""ToDo 一覧の絞り込み・並び替え・キーセット(AP-TODO-06、§9.3 一覧、§10 #11 / #12 / #13)のテスト(サービス層)。

並び順の期待値(オラクル)は、仕様から Python で計算する(``due_date``: 期限なしは昇順で末尾・降順で先頭、``priority``: low < medium < high、
同じ値は ``id`` 順)。値の重複(同じ期限・優先度・作成日時)を含むデータで、全キー・昇降順・複数の ``limit`` でページを辿り、重複・欠落が無いことを確認する。
"""
import datetime as dt
import uuid

import pytest
import pytest_check as check

from main_app.services.errors import TodoValidationError

RANK = {"low": 1, "medium": 2, "high": 3}
T0 = dt.datetime(2026, 3, 1, 9, 0, tzinfo=dt.UTC)


def day(offset: int) -> dt.date:
    return dt.date(2030, 6, 10) + dt.timedelta(days=offset)


@pytest.fixture
def dataset(world):
    """値が重複する 14 件の ToDo(tenant 公開 = 全員が閲覧可)。``rows``: ID → 期待値の元データ。"""
    specs = [
        # title, status, priority, due offset, created offset(秒), updated offset(秒)
        ("Alpha report", "open", "low", None, 0, 0),
        ("Beta report", "open", "medium", 0, 0, 5),
        ("Gamma", "in_progress", "high", 0, 1, 5),
        ("Delta", "done", "low", 1, 1, 9),
        ("Epsilon report", "done", "medium", 1, 2, 9),
        ("Zeta", "open", "high", 2, 2, 9),
        ("Eta", "in_progress", "low", None, 3, 3),
        ("Theta report", "in_progress", "medium", None, 3, 3),
        ("Iota", "done", "high", 3, 4, 4),
        ("Kappa", "open", "low", 3, 4, 8),
        ("Lambda report", "open", "medium", 4, 5, 8),
        ("Mu", "done", "high", 5, 5, 8),
        ("Nu", "in_progress", "low", 5, 6, 1),
        ("Xi report", "open", "high", None, 6, 1),
    ]
    rows = {}
    for title, status, priority, due, created, updated in specs:
        todo_id = world.factory.add(
            world.ctx, world.creator, title=title, status=status, priority=priority, due_date=None if due is None else day(due), visibility="tenant",
            created_at=T0 + dt.timedelta(seconds=created), updated_at=T0 + dt.timedelta(seconds=updated),
        )
        rows[todo_id] = {"title": title, "status": status, "priority": priority, "due_date": None if due is None else day(due), "created_at": T0 + dt.timedelta(seconds=created), "updated_at": T0 + dt.timedelta(seconds=updated)}
    return rows


def oracle_order(rows: dict, key: str, descending: bool) -> list[uuid.UUID]:
    """仕様から計算した並び順。"""

    def sort_key(todo_id):
        value = rows[todo_id][key]
        if key == "due_date":
            return (value is None, value or dt.date.min, todo_id)  # 昇順: 期限なしは末尾
        if key == "priority":
            return (RANK[value], todo_id)
        return (value, todo_id)

    return sorted(rows, key=sort_key, reverse=descending)


def walk(world, person, *, limit, sort, **filters) -> list:
    """全ページを辿った ToDo の ID(出現順)。ページごとの件数も検証する。"""
    ids, after = [], None
    with world.service(person) as service:
        for _ in range(100):
            page = service.list_todos(limit=limit, sort=sort, after=after, **filters)
            check.is_true(len(page.items) <= limit)
            ids.extend(item.id for item in page.items)
            after = page.next_after
            if after is None:
                break
            check.equal(len(page.items), limit, "最後以外のページは limit 件")
    return ids


class TestSortAndKeyset:
    """全ソートキー × 昇降順 × ページサイズで、オラクルと同じ順序で重複・欠落なく辿れる。"""

    @pytest.mark.parametrize("limit", [1, 3, 5, 14, 50])
    @pytest.mark.parametrize("key", ["due_date", "priority", "created_at", "updated_at"])
    @pytest.mark.parametrize("descending", [False, True])
    def test_order_and_paging(self, world, dataset, key, descending, limit):
        """どのキー・向き・件数でも、全ページを辿った並びは期待どおり(同じ値は id 順)で、重複・欠落が無い。"""
        sort = f"{'-' if descending else ''}{key}"
        ids = walk(world, world.admin, limit=limit, sort=sort)
        check.equal(ids, oracle_order(dataset, key, descending))
        check.equal(len(ids), len(set(ids)))

    def test_default_sort_is_newest_created_first(self, world, dataset):
        """sort を省略すると -created_at。"""
        with world.service(world.admin) as service:
            ids = [item.id for item in service.list_todos(limit=50).items]
        check.equal(ids, oracle_order(dataset, "created_at", True))

    def test_due_date_nulls_position(self, world, dataset):
        """期限なしは昇順で末尾、降順で先頭(§10 #11)。"""
        with world.service(world.admin) as service:
            asc = [item.due_date for item in service.list_todos(limit=50, sort="due_date").items]
            desc = [item.due_date for item in service.list_todos(limit=50, sort="-due_date").items]
        check.equal((asc[-4:], asc[:-4].count(None)), ([None] * 4, 0))
        check.equal((desc[:4], desc[4:].count(None)), ([None] * 4, 0))

    def test_priority_order_is_low_medium_high(self, world, dataset):
        """priority は low < medium < high(文字列の辞書順 high < low < medium にならない)。"""
        with world.service(world.admin) as service:
            order = [item.priority.value for item in service.list_todos(limit=50, sort="priority").items]
        check.equal(sorted(order, key=RANK.get), order)
        check.equal(order[0], "low")
        check.equal(order[-1], "high")

    def test_next_after_value_types(self, world, dataset):
        """next_after の値の型: due_date は date | None、priority は値の文字列、created_at / updated_at は datetime(§9.3)。"""
        with world.service(world.admin) as service:
            check.is_instance(service.list_todos(limit=2, sort="due_date").next_after[0], dt.date)
            check.is_none(service.list_todos(limit=2, sort="-due_date").next_after[0])
            check.is_instance(service.list_todos(limit=2, sort="priority").next_after[0], str)
            check.is_instance(service.list_todos(limit=2, sort="created_at").next_after[0], dt.datetime)
            check.is_instance(service.list_todos(limit=2, sort="-updated_at").next_after[0], dt.datetime)

    def test_after_accepts_iso_strings(self, world, dataset):
        """after の値は ISO 8601 の文字列でも受け付ける(due_date は日付、created_at はタイムゾーン付きの日時)。"""
        with world.service(world.admin) as service:
            page = service.list_todos(limit=3, sort="due_date")
            as_text = (page.next_after[0].isoformat(), page.next_after[1])
            check.equal([i.id for i in service.list_todos(limit=50, sort="due_date", after=as_text).items], [i.id for i in service.list_todos(limit=50, sort="due_date", after=page.next_after).items])
            page = service.list_todos(limit=3, sort="created_at")
            as_text = (page.next_after[0].isoformat(), str(page.next_after[1]))
            check.equal([i.id for i in service.list_todos(limit=50, sort="created_at", after=as_text).items], [i.id for i in service.list_todos(limit=50, sort="created_at", after=page.next_after).items])

    def test_exact_page_boundary_has_no_extra_page(self, world, dataset):
        """件数がちょうど limit の倍数のとき、最後のページの next_after は None(空のページを返さない)。"""
        with world.service(world.admin) as service:
            page = service.list_todos(limit=14, sort="priority")
            check.equal((len(page.items), page.next_after), (14, None))
            page = service.list_todos(limit=7, sort="priority")
            check.is_not_none(page.next_after)
            check.equal(len(service.list_todos(limit=7, sort="priority", after=page.next_after).items), 7)

    @pytest.mark.parametrize(
        ("sort", "after"),
        [
            ("created_at", "x"),
            ("created_at", (1,)),
            ("created_at", ("2026-01-01T00:00:00", str(uuid.uuid4()))),
            ("created_at", (dt.datetime(2026, 1, 1), str(uuid.uuid4()))),
            ("created_at", ("2026-01-01T00:00:00+00:00", "not-uuid")),
            ("priority", ("urgent", str(uuid.uuid4()))),
            ("priority", (3, str(uuid.uuid4()))),
            ("due_date", ("not-a-date", str(uuid.uuid4()))),
            ("due_date", (dt.datetime(2030, 1, 1, tzinfo=dt.UTC), str(uuid.uuid4()))),
        ],
    )
    def test_invalid_after_is_cursor_error(self, world, dataset, sort, after):
        """起点の型・形式が並び替えキーに合わなければ TodoValidationError(field=cursor)。"""
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.admin, lambda s: s.list_todos(sort=sort, after=after))
        check.equal(caught.value.field, "cursor")

    def test_limit_is_clamped(self, world, dataset):
        """limit は 1〜200 に補正される(0 や負数は 1 件、極端に大きい値は 200 件まで)。"""
        check.equal(len(world.call(world.admin, lambda s: s.list_todos(limit=0)).items), 1)
        check.equal(len(world.call(world.admin, lambda s: s.list_todos(limit=-5)).items), 1)
        check.equal(len(world.call(world.admin, lambda s: s.list_todos(limit=100000)).items), 14)

    def test_list_items_do_not_load_description(self, world):
        """一覧の要素は説明を含まない(TodoView に description 属性が無い)。詳細にはある。"""
        todo_id = world.factory.add(world.ctx, world.creator, description="body", visibility="tenant")
        item = world.call(world.admin, lambda s: s.list_todos()).items[0]
        check.is_false(hasattr(item, "description"))
        check.equal(world.call(world.admin, lambda s: s.get_todo(todo_id)).description, "body")


class TestFilters:
    """絞り込み(AP-TODO-06、§10 #12)。"""

    def titles(self, world, **filters) -> set[str]:
        return {item.title for item in world.call(world.admin, lambda s: s.list_todos(limit=200, **filters)).items}

    def test_status_single_and_multiple(self, world, dataset):
        """status は 1 つ(文字列)でも複数(リスト)でも絞り込める。重複は無視する。"""
        expected_open = {r["title"] for r in dataset.values() if r["status"] == "open"}
        check.equal(self.titles(world, status="open"), expected_open)
        check.equal(self.titles(world, status=["open", "done", "open"]), {r["title"] for r in dataset.values() if r["status"] in ("open", "done")})
        check.equal(self.titles(world, status=[]), {r["title"] for r in dataset.values()})

    def test_priority_multiple(self, world, dataset):
        """priority の複数指定はいずれかに一致。"""
        check.equal(self.titles(world, priority=["medium", "high"]), {r["title"] for r in dataset.values() if r["priority"] in ("medium", "high")})

    def test_combination_is_and(self, world, dataset):
        """複数の絞り込みは AND。"""
        expected = {r["title"] for r in dataset.values() if r["status"] == "open" and r["priority"] in ("low", "high")}
        check.equal(self.titles(world, status=["open"], priority=["low", "high"]), expected)

    def test_due_before_and_after_are_inclusive_and_exclude_null(self, world, dataset):
        """due_before / due_after は指定日を含み、期限なしは除く(§10 #12)。両方指定で範囲になる。"""
        rows = list(dataset.values())
        check.equal(self.titles(world, due_before=day(1)), {r["title"] for r in rows if r["due_date"] is not None and r["due_date"] <= day(1)})
        check.equal(self.titles(world, due_after=day(3)), {r["title"] for r in rows if r["due_date"] is not None and r["due_date"] >= day(3)})
        check.equal(self.titles(world, due_after=day(1), due_before=day(3)), {r["title"] for r in rows if r["due_date"] is not None and day(1) <= r["due_date"] <= day(3)})
        check.equal(self.titles(world, due_after=day(3), due_before=day(1)), set())
        check.equal(self.titles(world, due_after=day(2), due_before=day(2)), {"Zeta"})

    def test_q_is_case_insensitive_partial_match(self, world, dataset):
        """q はタイトルの部分一致(大文字小文字を区別しない)。前後の空白は無視し、空なら絞り込まない。"""
        expected = {r["title"] for r in dataset.values() if "report" in r["title"].lower()}
        check.equal(self.titles(world, q="REPORT"), expected)
        check.equal(self.titles(world, q="  report "), expected)
        check.equal(self.titles(world, q="   "), {r["title"] for r in dataset.values()})
        check.equal(self.titles(world, q="eta"), {"Beta report", "Zeta", "Eta", "Theta report"})
        check.equal(self.titles(world, q="no-such-title"), set())

    def test_q_treats_like_wildcards_literally(self, world):
        """q の % _ \\ はワイルドカードではなく文字そのものとして一致する(全件にヒットしない)。"""
        for title in ("100% done", "snake_case", "back\\slash", "plain text", "1000 done", "snakeXcase"):
            world.factory.add(world.ctx, world.creator, title=title, visibility="tenant")
        check.equal(self.titles(world, q="%"), {"100% done"})
        check.equal(self.titles(world, q="_"), {"snake_case"})
        check.equal(self.titles(world, q="e_c"), {"snake_case"})
        check.equal(self.titles(world, q="\\"), {"back\\slash"})
        check.equal(self.titles(world, q="0% d"), {"100% done"})

    def test_assignee_filter(self, world):
        """assignee_id は担当者に含まれる ToDo。無効化されたユーザーでも絞り込める。"""
        a = world.factory.add(world.ctx, world.creator, title="a", visibility="tenant", assignees=[world.assignee, world.inactive])
        world.factory.add(world.ctx, world.creator, title="b", visibility="tenant", assignees=[world.m1])
        world.factory.add(world.ctx, world.creator, title="c", visibility="tenant")
        check.equal(self.titles(world, assignee_id=world.assignee.id), {"a"})
        check.equal(self.titles(world, assignee_id=world.inactive.id), {"a"})
        check.equal(self.titles(world, assignee_id=uuid.uuid4()), set())
        del a

    def test_organization_filter_uses_only_active_organizations(self, world):
        """organization_id は公開先に含まれる有効な組織で絞り込む。削除済みの組織・organization 以外の閲覧範囲は対象外。"""
        world.factory.add(world.ctx, world.creator, title="o1 only", visibility="organization", orgs=[world.o1])
        world.factory.add(world.ctx, world.creator, title="o1 and o2", visibility="organization", orgs=[world.o1, world.o2])
        world.factory.add(world.ctx, world.creator, title="o3 deleted", visibility="organization", orgs=[world.o3])
        world.factory.add(world.ctx, world.creator, title="tenant with link", visibility="tenant", orgs=[world.o1])
        check.equal(self.titles(world, organization_id=world.o1), {"o1 only", "o1 and o2"})
        check.equal(self.titles(world, organization_id=world.o2), {"o1 and o2"})
        check.equal(self.titles(world, organization_id=world.o3), set())

    def test_filters_with_scope_and_paging(self, world, dataset):
        """絞り込み + scope + ページングを組み合わせても、重複・欠落なく辿れる。"""
        ids = walk(world, world.admin, limit=2, sort="-priority", status=["open", "in_progress"], scope="shared")
        expected = [i for i in oracle_order(dataset, "priority", True) if dataset[i]["status"] in ("open", "in_progress")]
        check.equal(ids, expected)

    @pytest.mark.parametrize(
        ("kwargs", "field", "reason"),
        [
            ({"scope": "everything"}, "scope", "unsupported"),
            ({"status": ["bogus"]}, "status", "unsupported"),
            ({"status": "open,done"}, "status", "unsupported"),
            ({"priority": ["urgent"]}, "priority", "unsupported"),
            ({"priority": 5}, "priority", "type"),
            ({"sort": "title"}, "sort", "unsupported"),
            ({"sort": "due_date,-priority"}, "sort", "unsupported"),
            ({"sort": ""}, "sort", "unsupported"),
            ({"q": "x" * 201}, "q", "too_long"),
            ({"q": "a\x00b"}, "q", "format"),
            ({"q": 5}, "q", "type"),
            ({"due_before": dt.datetime(2030, 1, 1, tzinfo=dt.UTC)}, "due_before", "type"),
            ({"due_after": "2030-01-01"}, "due_after", "type"),
            ({"assignee_id": "not-uuid"}, "assignee_id", "format"),
            ({"organization_id": "not-uuid"}, "organization_id", "format"),
        ],
    )
    def test_invalid_arguments(self, world, kwargs, field, reason):
        """不正な引数は TodoValidationError(項目と理由付き)。"""
        with pytest.raises(TodoValidationError) as caught:
            world.call(world.admin, lambda s: s.list_todos(**kwargs))
        check.equal((caught.value.field, caught.value.reason), (field, reason))
