# -*- coding: utf-8 -*-
"""GET /api/v1/cp/tenants の primary_metrics(テーマ固有の主要指標。01 §13 #5、CP-MET-02)のテスト。

主要指標は ``modules/tenant_metrics/registry.py`` に登録されたテーマの宣言(ToDo アプリでは ``todo_count``)から決まり、
値は直近の日次メトリクス(``t_tenant_daily_metric``)から引く。使い捨てのテナントと日次メトリクスを作り、``cp_db`` が後片付けする。
"""
import datetime as dt

import pytest
import pytest_check as check

from control_plane_app.api_tenants import paging
from modules.tenant_metrics.registry import theme_primary_metric_keys

from .conftest import insert_metric

TENANTS = "/api/v1/cp/tenants"
TODAY = dt.datetime.now(dt.UTC).date()


def list_items(client, headers) -> dict[str, dict]:
    """全ページを辿り、ID → 要素 の辞書を返す。"""
    items, cursor = {}, None
    for _ in range(200):
        response = client.get(TENANTS, headers=headers, params={"limit": 200, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        body = response.json()
        items.update({item["id"]: item for item in body["items"]})
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("カーソルが終わらない")


def test_theme_declares_todo_count_as_primary_metric():
    """ToDo テーマは主要指標として todo_count を宣言している(一覧に出す指標の元)。"""
    check.equal(theme_primary_metric_keys(), ("todo_count",))


def test_every_item_has_primary_metrics_in_declared_order(client, viewer, cp_db):
    """全要素が primary_metrics を持ち、テーマが宣言したキーを宣言の順に含む(集計前でも要素は欠けない)。"""
    cp_db.insert_tenant()
    items = list_items(client, viewer)
    for item in items.values():
        check.equal([m["metric_key"] for m in item["primary_metrics"]], list(theme_primary_metric_keys()))
        for metric in item["primary_metrics"]:
            check.equal(set(metric), {"metric_key", "value", "date"})


def test_value_is_null_before_first_snapshot(client, viewer, cp_db):
    """日次スナップショットがまだ無いテナントは、value と date が null(0 ではない)。"""
    tenant_id = cp_db.insert_tenant()
    item = list_items(client, viewer)[str(tenant_id)]
    check.equal(item["primary_metrics"], [{"metric_key": "todo_count", "value": None, "date": None}])


def test_latest_snapshot_value_and_date(client, viewer, cp_db):
    """値は直近の日の値(10 進数の文字列)で、date はその集計対象日。古い日の値は使わない。"""
    tenant_id = cp_db.insert_tenant()
    insert_metric(cp_db, tenant_id, TODAY - dt.timedelta(days=3), "todo_count", 4)
    insert_metric(cp_db, tenant_id, TODAY - dt.timedelta(days=1), "todo_count", 11)
    item = list_items(client, viewer)[str(tenant_id)]
    check.equal(item["primary_metrics"], [{"metric_key": "todo_count", "value": "11", "date": (TODAY - dt.timedelta(days=1)).isoformat()}])


def test_zero_is_reported_as_zero(client, viewer, cp_db):
    """集計結果が 0 件のテナントは value が "0"(集計前の null と区別できる)。"""
    tenant_id = cp_db.insert_tenant()
    insert_metric(cp_db, tenant_id, TODAY, "todo_count", 0)
    item = list_items(client, viewer)[str(tenant_id)]
    check.equal(item["primary_metrics"][0]["value"], "0")


def test_metrics_of_other_tenants_are_not_mixed(client, viewer, cp_db):
    """テナントごとに自分の値が出る(別のテナントの値と混ざらない)。基盤のユーザー数の指標とも独立している。"""
    first, second, empty = cp_db.insert_tenant(), cp_db.insert_tenant(), cp_db.insert_tenant()
    insert_metric(cp_db, first, TODAY, "todo_count", 3)
    insert_metric(cp_db, first, TODAY, "users_total", 100)
    insert_metric(cp_db, second, TODAY, "todo_count", 8)
    items = list_items(client, viewer)
    check.equal([m["value"] for m in items[str(first)]["primary_metrics"]], ["3"])
    check.equal([m["value"] for m in items[str(second)]["primary_metrics"]], ["8"])
    check.equal([m["value"] for m in items[str(empty)]["primary_metrics"]], [None])
    check.equal((items[str(first)]["users_total"], items[str(second)]["users_total"]), (100, None))


def test_non_primary_metrics_are_not_listed(client, viewer, cp_db):
    """主要指標として宣言されていない指標(todo_open_count 等)は、日次メトリクスにあっても primary_metrics に出さない。"""
    tenant_id = cp_db.insert_tenant()
    insert_metric(cp_db, tenant_id, TODAY, "todo_open_count", 5)
    insert_metric(cp_db, tenant_id, TODAY, "todo_count", 6)
    item = list_items(client, viewer)[str(tenant_id)]
    check.equal([m["metric_key"] for m in item["primary_metrics"]], ["todo_count"])


def test_primary_metrics_on_every_page(client, viewer, cp_db):
    """ページングしても、どのページの要素にも primary_metrics が付く。"""
    ids = [cp_db.insert_tenant() for _ in range(3)]
    for index, tenant_id in enumerate(ids):
        insert_metric(cp_db, tenant_id, TODAY, "todo_count", index + 1)
    cursor, seen = None, {}
    for _ in range(200):
        body = client.get(TENANTS, headers=viewer, params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        for item in body["items"]:
            check.is_true(len(item["primary_metrics"]) == 1)
            seen[item["id"]] = item["primary_metrics"][0]["value"]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    check.equal([seen[str(i)] for i in ids], ["1", "2", "3"])


@pytest.mark.parametrize(
    ("declared", "values", "expected"),
    [
        ((), {}, []),
        (("b_metric", "a_metric"), {"a_metric": 2, "b_metric": 1}, [("b_metric", "1"), ("a_metric", "2")]),
        (("a_metric", "b_metric"), {"b_metric": 7}, [("a_metric", None), ("b_metric", "7")]),
    ],
    ids=["none-declared", "declared-order", "partially-collected"],
)
def test_follows_theme_declaration(client, viewer, cp_db, monkeypatch, declared, values, expected):
    """テーマが宣言していなければ空配列、複数宣言していれば宣言の順。集計済みの指標だけ値が入り、未集計は null。"""
    monkeypatch.setattr(paging, "theme_primary_metric_keys", lambda: declared)
    tenant_id = cp_db.insert_tenant()
    for key, value in values.items():
        insert_metric(cp_db, tenant_id, TODAY, key, value)
    item = list_items(client, viewer)[str(tenant_id)]
    check.equal([(m["metric_key"], m["value"]) for m in item["primary_metrics"]], expected)


def test_requires_cp_session(client, login_ap, seeded):
    """CP のセッションが必要(未認証・AP のセッションは 401)。"""
    check.equal(client.get(TENANTS).status_code, 401)
    check.equal(client.get(TENANTS, headers=login_ap("alpha", seeded("alpha").tenant_id)).status_code, 401)
