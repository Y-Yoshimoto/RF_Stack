# -*- coding: utf-8 -*-
"""チェックリストの同時実行(2 つ以上のセッション。ToDoApp.md §9.3: 変更系は ``t_todo`` を ``FOR UPDATE`` で直列化する)のテスト。

スレッドごとに別のセッション(別の接続)で同じ ToDo を同時に変更し、上限(100)・position の連番・版が壊れないことを確認する。
``threading.Barrier`` で開始をそろえる。結果の件数は決定的(どの順で勝つかには依存しない)。
"""
import concurrent.futures
import threading

import pytest
import pytest_check as check
from sqlalchemy import text

from main_app.models import TTodoChecklistItem
from main_app.models.todo import TODO_CHECKLIST_ITEMS_MAX
from main_app.services.errors import TodoChecklistVersionConflictError, TodoValidationError


@pytest.fixture
def todo(world):
    return world.factory.add(world.ctx, world.creator, title="concurrent", visibility="tenant", assignees=[world.assignee])


def run_concurrently(funcs):
    """``funcs`` を別スレッド(別セッション)で同時に呼び、結果(または例外)を順に返す。"""
    barrier = threading.Barrier(len(funcs))

    def wrap(func):
        barrier.wait()
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 結果として検査する
            return exc

    with concurrent.futures.ThreadPoolExecutor(len(funcs)) as pool:
        return list(pool.map(wrap, funcs))


def seed_items(world, todo_id, count):
    with world.ap_db.session(world.ctx) as session:
        session.add_all([TTodoChecklistItem(tenant_id=world.ctx.tenant_id, todo_id=todo_id, title=f"s{i}", position=i, created_by=world.creator.id, updated_by=world.creator.id) for i in range(count)])
        session.commit()
    with world.ap_db.session(world.ctx) as session:
        session.execute(text("UPDATE t_todo SET checklist_version = :v WHERE id = :id"), {"v": count + 1, "id": todo_id})
        session.commit()


def test_concurrent_adds_keep_positions_contiguous(world, todo):
    """6 つのセッションが同時に 1 件ずつ追加しても、全て成功し、position は 0..5 の連番、checklist_version は 7(追加の数だけ +1)。"""
    funcs = [lambda i=i: world.checklist_call(world.creator, lambda s: s.add_item(todo, title=f"item {i}")) for i in range(6)]
    results = run_concurrently(funcs)
    check.equal([type(r).__name__ for r in results], ["TodoChecklistView"] * 6)
    rows = world.item_rows(todo)
    check.equal(([r["position"] for r in rows], len({r["title"] for r in rows})), (list(range(6)), 6))
    check.equal(world.todo(todo)["checklist_version"], 7)
    check.equal(len(world.checklist_activities(todo)), 6)


def test_concurrent_inserts_at_the_same_position(world, todo):
    """先頭への挿入を同時に行っても、位置の重複・欠番が起きない(一意制約違反にならない)。"""
    world.checklist_call(world.creator, lambda s: s.add_item(todo, title="base"))
    funcs = [lambda i=i: world.checklist_call(world.admin, lambda s: s.add_item(todo, title=f"head {i}", position=0)) for i in range(4)]
    results = run_concurrently(funcs)
    check.equal([type(r).__name__ for r in results], ["TodoChecklistView"] * 4)
    check.equal([r["position"] for r in world.item_rows(todo)], list(range(5)))
    check.equal(world.item_rows(todo)[-1]["title"], "base")


def test_concurrent_adds_cannot_exceed_the_limit(world, todo):
    """98 件の状態で 4 つのセッションが同時に追加すると、成功は 2 件だけで、残りは too_many。合計は 100 件を超えず、position は 0..99。"""
    seed_items(world, todo, TODO_CHECKLIST_ITEMS_MAX - 2)
    funcs = [lambda i=i: world.checklist_call(world.creator, lambda s: s.add_item(todo, title=f"late {i}")) for i in range(4)]
    results = run_concurrently(funcs)
    errors = [r for r in results if isinstance(r, Exception)]
    check.equal(len(errors) + sum(1 for r in results if not isinstance(r, Exception)), 4)
    check.equal(len(errors), 2)
    check.is_true(all(isinstance(e, TodoValidationError) and (e.field, e.reason) == ("items", "too_many") for e in errors), [repr(e) for e in errors])
    check.equal([r["position"] for r in world.item_rows(todo)], list(range(TODO_CHECKLIST_ITEMS_MAX)))
    check.equal(world.todo(todo)["checklist_version"], TODO_CHECKLIST_ITEMS_MAX + 1)


def test_concurrent_reorders_with_same_version_only_one_wins(world, todo):
    """同じチェックリストの版を期待した 2 つの並べ替えのうち、成功は 1 つだけで、もう 1 つは 412(target = checklist)。"""
    view = None
    for title in ("a", "b", "c"):
        view = world.checklist_call(world.creator, lambda s, title=title: s.add_item(todo, title=title))
    ids = [i.id for i in view.items]
    orders = [list(reversed(ids)), [ids[1], ids[2], ids[0]]]
    results = run_concurrently([lambda order=order: world.checklist_call(world.creator, lambda s: s.reorder_items(todo, expected_version=view.version, item_ids=order)) for order in orders])
    losers = [r for r in results if isinstance(r, Exception)]
    check.equal(len(losers), 1)
    check.is_true(isinstance(losers[0], TodoChecklistVersionConflictError) and losers[0].target == "checklist", repr(losers))
    check.equal(world.todo(todo)["checklist_version"], view.version + 1)
    check.equal([r["position"] for r in world.item_rows(todo)], [0, 1, 2])


def test_concurrent_item_updates_with_same_item_version_only_one_wins(world, todo):
    """同じ項目の版を期待した名前変更と完了の切り替えが同時に走ると、1 つだけ成功し、もう 1 つは 412(target = item)。項目の版は +1 だけ。"""
    item = world.checklist_call(world.creator, lambda s: s.add_item(todo, title="x")).items[0]
    results = run_concurrently(
        [
            lambda: world.checklist_call(world.creator, lambda s: s.update_item(todo, item.id, expected_version=1, title="renamed")),
            lambda: world.checklist_call(world.assignee, lambda s: s.update_item(todo, item.id, expected_version=1, is_done=True)),
        ]
    )
    losers = [r for r in results if isinstance(r, Exception)]
    check.equal(len(losers), 1)
    check.is_true(isinstance(losers[0], TodoChecklistVersionConflictError) and losers[0].target == "item", repr(losers))
    check.equal(world.item_rows(todo)[0]["version"], 2)


def test_concurrent_add_and_delete_keep_positions_contiguous(world, todo):
    """削除(詰め直し)と追加が同時に走っても、position は 0 からの連番のまま(欠番・重複なし)。"""
    view = None
    for title in ("a", "b", "c", "d"):
        view = world.checklist_call(world.creator, lambda s, title=title: s.add_item(todo, title=title))
    victim = view.items[1]
    funcs = [
        lambda: world.checklist_call(world.creator, lambda s: s.delete_item(todo, victim.id, expected_version=victim.version)),
        lambda: world.checklist_call(world.creator, lambda s: s.add_item(todo, title="e")),
        lambda: world.checklist_call(world.admin, lambda s: s.add_item(todo, title="f", position=0)),
    ]
    results = run_concurrently(funcs)
    check.equal([r for r in results if isinstance(r, Exception)], [])
    rows = world.item_rows(todo)
    check.equal(([r["position"] for r in rows], len(rows)), (list(range(5)), 5))
    check.equal(world.todo(todo)["checklist_version"], view.version + 3, "削除 1 回 + 追加 2 回")


def test_add_and_todo_edit_at_the_same_time_both_succeed(world, todo):
    """チェックリストの追加と ToDo 本体の編集が同時に走っても、どちらも成功する(版は別。本体の版 +1、checklist_version +1)。"""
    funcs = [
        lambda: world.checklist_call(world.creator, lambda s: s.add_item(todo, title="x")),
        lambda: world.call(world.creator, lambda s: s.update_todo(todo, expected_version=1, title="renamed")),
    ]
    results = run_concurrently(funcs)
    check.equal([r for r in results if isinstance(r, Exception)], [])
    row = world.todo(todo)
    check.equal((row["title"], row["version"], row["checklist_version"]), ("renamed", 2, 2))
