# -*- coding: utf-8 -*-
"""ToDo 一覧の性能の目安(ToDoApp.md §5 / §9.3: 1 ページあたり 5 クエリ(v0.5 は 3)、N+1 にしない)。

1 つの使い捨てテナントに数千件を投入し、一覧で実行された SQL の数が件数・ページサイズに依存せず一定であることを確認する。
実行時間は上限をテストにしない(計測値を ``record_property`` と標準出力に残す。``pytest -s`` で確認できる)。
"""
import re
import time

import pytest
import pytest_check as check
from sqlalchemy import event

SEED_FIRST = 500
SEED_TOTAL = 3000
# 一覧 1 回の想定: ToDo 本体 + 担当者 + 公開先組織 = 3 クエリ(+ トランザクション開始時の GUC 設定 1 回)
# v0.6(AP-UX-03)で、件数(チェックリストの進捗・コメント数。load_todo_counters)と作成者・更新者の表示名の 2 クエリが加わり 5 クエリ。
# 余裕は従来と同じ 2(include_total=True のときの総件数 1 クエリもこの範囲に収まる)
QUERIES_PER_LIST = 5
MAX_QUERIES_PER_LIST = 7


class QueryCounter:
    """エンジンで実行された SQL を記録する。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.statements: list[str] = []

    def _record(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(statement)

    def __enter__(self) -> "QueryCounter":
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info) -> None:
        event.remove(self.engine, "before_cursor_execute", self._record)

    @property
    def data_queries(self) -> list[str]:
        """GUC の設定(set_config)を除いた SQL。"""
        return [s for s in self.statements if "set_config" not in s.lower()]


@pytest.fixture
def big_world(world):
    """担当者候補 6 人(m1 を含む)・公開先組織 4 つを用意し、SEED_FIRST 件を投入した状態。"""
    people = [world.add_person(f"p{i}") for i in range(5)] + [world.m1]
    orgs = [world.ap_db.add_org(world.ctx, f"Perf Org {i}", members=(world.m1.id,) if i % 2 == 0 else (world.m2.id,)).id for i in range(4)]
    world.perf_people, world.perf_orgs = people, orgs
    world.perf_ids = world.factory.bulk(world.ctx, world.creator, SEED_FIRST, assignee_pool=people, org_pool=orgs)
    return world


def measure(world, person, **kwargs):
    """一覧を 1 回実行し、(SQL の数, 秒, 返った件数) を返す。"""
    with world.service(person) as service, QueryCounter(world.ap_db.runtime) as counter:
        started = time.perf_counter()
        page = service.list_todos(**kwargs)
        elapsed = time.perf_counter() - started
    return len(counter.data_queries), elapsed, len(page.items), counter


def test_query_count_is_constant_regardless_of_rows_and_page_size(big_world, record_property):
    """件数(500 → 3000)・ページサイズ(10 / 50 / 200)・操作者(管理者 / 組織所属の member)・並び順・絞り込みを変えても、一覧の SQL の数は同じ(N+1 が無い)。"""
    world = big_world
    cases = {
        "admin default": (world.admin, {"limit": 50}),
        "admin limit 10": (world.admin, {"limit": 10}),
        "admin limit 200": (world.admin, {"limit": 200}),
        "member (org/tenant visibility) default": (world.m1, {"limit": 50}),
        "member limit 200 sort priority": (world.m1, {"limit": 200, "sort": "-priority"}),
        "member filters": (world.m1, {"limit": 50, "status": ["in_progress"], "q": "bulk", "organization_id": world.perf_orgs[0], "sort": "due_date"}),
        "member assigned scope": (world.m1, {"limit": 50, "scope": "assigned"}),
    }
    small = {name: measure(world, person, **kwargs) for name, (person, kwargs) in cases.items()}
    world.factory.bulk(world.ctx, world.creator, SEED_TOTAL - SEED_FIRST, assignee_pool=world.perf_people, org_pool=world.perf_orgs)
    large = {name: measure(world, person, **kwargs) for name, (person, kwargs) in cases.items()}
    for name in cases:
        small_count, small_time, small_rows, _ = small[name]
        large_count, large_time, large_rows, counter = large[name]
        check.equal(large_count, small_count, f"{name}: 件数が増えても SQL の数は同じ")
        check.less_equal(large_count, MAX_QUERIES_PER_LIST, f"{name}: 想定は {QUERIES_PER_LIST} クエリ(実測 {large_count})\n" + "\n".join(counter.data_queries))
        check.greater(large_rows, 0, name)
        record_property(f"{name}", f"queries={large_count} rows={large_rows} time_ms={large_time * 1000:.1f} (500 rows: {small_time * 1000:.1f} ms)")
        print(f"[perf] {name}: queries={large_count} rows={large_rows} time={large_time * 1000:.1f}ms (at {SEED_FIRST} rows: {small_time * 1000:.1f}ms)")
    total = world.ap_db.rows(world.ctx, "SELECT count(*) AS n FROM t_todo")[0]["n"]
    check.equal(total, SEED_TOTAL)


def test_page_with_many_assignees_and_organizations_still_three_queries(big_world):
    """担当者・公開先組織を持つ ToDo が 200 件並ぶページでも、担当者・組織の取得は 1 回ずつ(ToDo ごとに引かない)。

    v0.6 で件数と作成者・更新者の表示名の 2 クエリが加わり、ページ全体は QUERIES_PER_LIST(5) クエリ(テスト名の 3 は v0.5 時点の値)。
    """
    world = big_world
    queries, _, rows, counter = measure(world, world.admin, limit=200, sort="created_at")
    check.equal(rows, 200)
    check.equal(queries, QUERIES_PER_LIST, "\n".join(counter.data_queries))
    tables = ["t_todo_assignee" in s for s in counter.data_queries], ["t_todo_organization" in s for s in counter.data_queries]
    check.equal((sum(tables[0]) >= 1, sum(tables[1]) >= 1), (True, True))
    assignee_statements = [s for s in counter.data_queries if "FROM t_todo_assignee" in s and "JOIN t_user" in s]
    check.equal(len(assignee_statements), 1)


def test_detail_and_activities_use_a_constant_number_of_queries(big_world):
    """詳細(ToDo + 担当者 + 組織)とアクティビティ一覧(アクティビティ + 操作者の表示名)も、件数に依存せず一定の SQL 数。"""
    world = big_world
    todo_id = world.perf_ids[1]
    for index in range(30):
        world.call(world.creator, lambda s, index=index: s.update_todo(todo_id, expected_version=index + 1, title=f"edit {index}"))
    with world.service(world.admin) as service, QueryCounter(world.ap_db.runtime) as counter:
        service.get_todo(todo_id)
    # 詳細: ToDo + 担当者 + 組織 + 件数 + 作成者・更新者の表示名 = 5 クエリ(v0.6 で 2 クエリ増。余裕 1 は従来どおり)
    check.less_equal(len(counter.data_queries), 6, "\n".join(counter.data_queries))
    with world.service(world.admin) as service, QueryCounter(world.ap_db.runtime) as counter:
        page = service.list_activities(todo_id, limit=200)
    check.equal(len(page.items), 30)
    check.less_equal(len(counter.data_queries), 3, "\n".join(counter.data_queries))


def test_visibility_condition_does_not_scan_per_row(big_world):
    """閲覧範囲の副問い合わせは相関しない(EXPLAIN に SubPlan の繰り返し評価が無い)。非管理者の一覧計画で、ToDo 本体の行ごとに担当者・組織を引く相関サブクエリが出ないことを確認する。"""
    from sqlalchemy import text
    from sqlmodel import col, select

    from main_app.models import TTodo
    from main_app.services.todo_policy import TodoActor, visible_condition

    world = big_world
    actor = TodoActor(tenant_id=world.ctx.tenant_id, user_id=world.m1.id, roles=frozenset({"member"}))
    statement = select(TTodo.id).where(col(TTodo.tenant_id) == world.ctx.tenant_id, col(TTodo.deleted_at).is_(None), visible_condition(actor))
    with world.ap_db.session(world.ctx) as session:
        compiled = statement.compile(dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True})
        plan = "\n".join(row[0] for row in session.connection().execute(text("EXPLAIN " + str(compiled))).all())
    check.is_none(re.search(r"(?<!hashed )SubPlan \d+\)", plan), plan)
    check.is_in("hashed SubPlan", plan)
