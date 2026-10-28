# -*- coding: utf-8 -*-
"""CP のテナント一覧(カーソル方式)・詳細・メトリクスのテスト。

一覧は開発 DB の全テナント(alpha / beta や他のテストのテナントを含む)を返すため、使い捨てテナントを複数作って
「自分の行が重複・欠落なく並ぶ」ことを確認する。
"""
import base64
import datetime as dt
import json
import uuid

import pytest
import pytest_check as check

from .conftest import insert_metric

TENANTS = "/api/v1/cp/tenants"
TODAY = dt.datetime.now(dt.UTC).date()


def traverse(client, headers, **params) -> tuple[list[dict], list[dict]]:
    """next_cursor を最後まで辿り、(全要素, 各ページのレスポンス本文) を返す。"""
    items, pages, cursor = [], [], None
    for _ in range(200):
        query = {**params, **({"cursor": cursor} if cursor else {})}
        response = client.get(TENANTS, headers=headers, params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body)
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items, pages
    raise AssertionError("カーソルが終わらない")


def make_cursor(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.fixture
def five_tenants(cp_db):
    """同じ名前の使い捨てテナント 5 件(並び替えキーの重複を作る)。名前は実行ごとに一意。"""
    name = f"Dup-{uuid.uuid4().hex[:8]}"
    ids = [cp_db.insert_tenant(name=name) for _ in range(5)]
    return name, ids


class TestListPagination:
    """カーソル方式のページネーション。"""

    @pytest.mark.parametrize("sort", ["-created_at", "created_at", "tenant_code", "-tenant_code", "name", "-name"])
    @pytest.mark.parametrize("limit", [1, 2, 3])
    def test_no_duplicates_and_no_gaps(self, client, viewer, five_tenants, sort, limit):
        """どの並び順・件数でも、全ページを辿ると自分の 5 件が欠落も重複もなく含まれ、全体で ID が重複しない。"""
        _, ids = five_tenants
        items, pages = traverse(client, viewer, limit=limit, sort=sort)
        listed = [item["id"] for item in items]
        check.equal(len(listed), len(set(listed)), "重複した行がある")
        for tenant_id in ids:
            check.equal(listed.count(str(tenant_id)), 1, f"{tenant_id} が {listed.count(str(tenant_id))} 回")
        check.is_true(all(len(page["items"]) <= limit for page in pages))
        check.is_true(all(page["next_cursor"] for page in pages[:-1]))
        check.is_none(pages[-1]["next_cursor"])

    def test_order_is_consistent_with_sort(self, client, viewer, five_tenants):
        """name 昇順・降順の並びは、ページをまたいでも同じ順序(同じ名前は id で安定)で、昇順と降順は逆順になる。"""
        name, ids = five_tenants
        asc, _ = traverse(client, viewer, limit=2, sort="name")
        desc, _ = traverse(client, viewer, limit=2, sort="-name")
        mine_asc = [i["id"] for i in asc if i["name"] == name]
        mine_desc = [i["id"] for i in desc if i["name"] == name]
        check.equal(mine_asc, sorted(mine_asc))
        check.equal(mine_desc, list(reversed(mine_asc)))

    def test_default_sort_is_newest_first(self, client, viewer, five_tenants):
        """既定は作成日時の新しい順。"""
        items, _ = traverse(client, viewer, limit=3)
        created = [i["created_at"] for i in items]
        check.equal(created, sorted(created, reverse=True))

    def test_first_page_without_cursor_and_limit_default(self, client, viewer):
        """limit の既定は 50 以下で、next_cursor が無ければ全件が 1 ページに収まる。"""
        body = client.get(TENANTS, headers=viewer).json()
        check.equal(set(body), {"items", "next_cursor", "total"})
        check.is_true(len(body["items"]) <= 50)

    def test_total_is_only_included_on_request(self, client, viewer, five_tenants):
        """total は include_total=true のときだけ入り、全ページを辿った件数と一致する。"""
        check.is_none(client.get(TENANTS, headers=viewer, params={"limit": 1}).json()["total"])
        items, pages = traverse(client, viewer, limit=2, include_total="true")
        check.equal(pages[0]["total"], len(items))
        check.is_true(all(page["total"] == pages[0]["total"] for page in pages))

    def test_status_filter(self, client, viewer, cp_db):
        """status で絞り込める(カンマ区切りで複数)。カーソルでも絞り込みが維持される。"""
        suspended = cp_db.insert_tenant(status="SUSPENDED")
        failed = cp_db.insert_tenant(status="FAILED")
        cp_db.insert_tenant(status="ACTIVE")
        items, _ = traverse(client, viewer, limit=1, status="SUSPENDED,FAILED")
        check.is_true(all(i["status"] in ("SUSPENDED", "FAILED") for i in items))
        check.is_true({str(suspended), str(failed)} <= {i["id"] for i in items})
        only, _ = traverse(client, viewer, status="FAILED", include_total="true")
        check.is_true(all(i["status"] == "FAILED" for i in only))

    def test_deleted_tenants_are_listed_without_filter(self, client, viewer, cp_db):
        """絞り込み無しなら削除済みも含まれる(台帳は残す)。"""
        deleted = cp_db.insert_tenant(status="DELETED")
        items, _ = traverse(client, viewer, limit=50)
        check.is_in(str(deleted), [i["id"] for i in items])

    def test_item_shape_hides_internal_columns(self, client, viewer, five_tenants):
        """要素に realm_name・tier・created_by・updated_by を含めない。日時は UTC(Z)。"""
        items, _ = traverse(client, viewer, limit=50)
        item = next(i for i in items if i["id"] == str(five_tenants[1][0]))
        check.equal(set(item), {"id", "tenant_code", "name", "status", "version", "created_at", "updated_at", "deletion_requested_at", "deleted_at", "users_total", "users_active", "metrics_date"})
        check.is_true(item["created_at"].endswith("Z"))
        check.is_none(item["users_total"])

    def test_users_metrics_come_from_the_latest_snapshot(self, client, viewer, cp_db):
        """一覧のユーザー数は、直近の日次メトリクス(最新日の値)。"""
        tenant_id = cp_db.insert_tenant()
        insert_metric(cp_db, tenant_id, TODAY - dt.timedelta(days=2), "users_total", 5)
        insert_metric(cp_db, tenant_id, TODAY - dt.timedelta(days=1), "users_total", 9)
        insert_metric(cp_db, tenant_id, TODAY - dt.timedelta(days=1), "users_active", 4)
        items, _ = traverse(client, viewer, limit=200)
        item = next(i for i in items if i["id"] == str(tenant_id))
        check.equal((item["users_total"], item["users_active"], item["metrics_date"]), (9, 4, (TODAY - dt.timedelta(days=1)).isoformat()))


class TestListValidation:
    """不正なクエリ・カーソル。"""

    def assert_field_error(self, response, field):
        check.equal(response.status_code, 422)
        body = response.json()
        check.equal(body["code"], "validation_error")
        check.is_in(field, [e["field"] for e in body["errors"]])

    @pytest.mark.parametrize("cursor", ["garbage", "!!!", "e30", "W10", "bnVsbA", "a" * 1025, "日本語"])
    def test_broken_cursor(self, client, viewer, cursor):
        """壊れたカーソル(base64 でない・JSON でない・オブジェクトでない・長すぎる)は 422 で field=cursor。500 にならない。"""
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"cursor": cursor}), "cursor")

    @pytest.mark.parametrize(
        "payload",
        [
            {"s": "-created_at", "k": "not-a-date", "i": str(uuid.uuid4())},
            {"s": "-created_at", "k": "2026-01-01T00:00:00", "i": str(uuid.uuid4())},  # タイムゾーンなし
            {"s": "-created_at", "k": "2026-01-01T00:00:00Z", "i": "not-a-uuid"},
            {"s": "-created_at", "k": 12345, "i": str(uuid.uuid4())},
            {"s": "-created_at", "k": None, "i": str(uuid.uuid4())},
            {"s": "-created_at"},
            {"k": "x", "i": str(uuid.uuid4())},
            {"s": ["-created_at"], "k": "x", "i": str(uuid.uuid4())},
            {"s": "-created_at", "k": {"$gt": ""}, "i": str(uuid.uuid4())},
        ],
    )
    def test_well_formed_but_invalid_cursor_content(self, client, viewer, payload):
        """JSON としては読めるが中身が不正なカーソルも 422(cursor)。"""
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"cursor": make_cursor(payload)}), "cursor")

    def test_cursor_from_another_sort_is_rejected(self, client, viewer, five_tenants):
        """並び替えの指定が変わったカーソルは 422(cursor)。"""
        first = client.get(TENANTS, headers=viewer, params={"limit": 1, "sort": "name"}).json()
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"cursor": first["next_cursor"], "sort": "-name"}), "cursor")
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"cursor": first["next_cursor"]}), "cursor")

    def test_sql_like_cursor_values_are_not_executed(self, client, viewer):
        """SQL を含む値のカーソルは、422 として拒否される(または空の結果)。いずれにしてもエラー詳細を返さない。"""
        payload = {"s": "name", "k": "x'; DROP TABLE t_tenant; --", "i": str(uuid.uuid4())}
        response = client.get(TENANTS, headers=viewer, params={"cursor": make_cursor(payload), "sort": "name"})
        check.is_in(response.status_code, (200, 422))
        check.is_not_in("DROP", response.text.replace("DROP TABLE t_tenant; --", "") if response.status_code == 200 else response.text)
        check.equal(client.get(TENANTS, headers=viewer).status_code, 200, "テーブルが無事")

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"limit": -1}, {"limit": "abc"}, {"limit": ""}])
    def test_invalid_limit(self, client, viewer, params):
        """limit が 1〜200 の整数でなければ 422。"""
        self.assert_field_error(client.get(TENANTS, headers=viewer, params=params), "limit")

    def test_limit_upper_bound_is_accepted(self, client, viewer):
        """limit=200 は受け付ける。"""
        check.equal(client.get(TENANTS, headers=viewer, params={"limit": 200}).status_code, 200)

    @pytest.mark.parametrize("sort", ["id", "-id", "status", "created_at;drop", "", "--created_at", "NAME", "name desc"])
    def test_invalid_sort(self, client, viewer, sort):
        """許可していない並び替えキーは 422(sort)。"""
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"sort": sort}), "sort")

    @pytest.mark.parametrize("status", ["UNKNOWN", "active", "ACTIVE,NOPE", "ACTIVE;DROP"])
    def test_invalid_status(self, client, viewer, status):
        """未知の状態(小文字を含む)は 422(status)。"""
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"status": status}), "status")

    def test_invalid_include_total(self, client, viewer):
        """include_total が真偽値でなければ 422。"""
        self.assert_field_error(client.get(TENANTS, headers=viewer, params={"include_total": "maybe"}), "include_total")


class TestDetail:
    """テナント詳細。"""

    def test_detail_with_history_and_etag(self, client, viewer, make_tenant):
        """詳細は払い出し履歴(新しい順)を含み、ETag はバージョンと一致する。一時パスワードは含まない。"""
        payload = make_tenant()
        tenant = payload["tenant"]
        response = client.get(f"{TENANTS}/{tenant['id']}", headers=viewer)
        check.equal(response.status_code, 200)
        body = response.json()
        check.equal(response.headers["ETag"], f'"{tenant["version"]}"')
        check.equal((body["id"], body["tenant_code"], body["status"], body["version"]), (tenant["id"], tenant["tenant_code"], "ACTIVE", tenant["version"]))
        check.equal([(h["type"], h["status"], h["step"]) for h in body["provisioning_history"]], [("onboard", "SUCCEEDED", "activate")])
        check.equal(body["provisioning_history"][0]["id"], payload["provisioning_history_id"])
        for forbidden in ("realm_name", "tier", "created_by", "updated_by", "temporary_password", "initial_admin"):
            check.is_not_in(forbidden, response.text)

    def test_etag_changes_after_update(self, client, viewer, admin, make_tenant):
        """更新(停止)の後、詳細の ETag が新しいバージョンになる。"""
        from .conftest import with_csrf

        tenant = make_tenant()["tenant"]
        client.post(f"{TENANTS}/{tenant['id']}/suspend", headers=with_csrf(admin, **{"If-Match": f'"{tenant["version"]}"'}))
        check.equal(client.get(f"{TENANTS}/{tenant['id']}", headers=viewer).headers["ETag"], f'"{tenant["version"] + 1}"')

    def test_unknown_tenant_is_404(self, client, viewer):
        """存在しないテナントは 404(tenant_not_found)。"""
        response = client.get(f"{TENANTS}/{uuid.uuid4()}", headers=viewer)
        check.equal((response.status_code, response.json()["code"]), (404, "tenant_not_found"))

    @pytest.mark.parametrize("value", ["not-a-uuid", "1234", "alpha", "00000000-0000-0000-0000-00000000000g"])
    def test_malformed_id_is_422(self, client, viewer, value):
        """UUID でない ID は 422(validation_error)。"""
        response = client.get(f"{TENANTS}/{value}", headers=viewer)
        check.equal((response.status_code, response.json()["code"]), (422, "validation_error"))


class TestMetrics:
    """メトリクス。"""

    def test_empty_when_no_data_with_default_window(self, client, viewer, cp_db):
        """集計データが無ければ items は空。期間の既定は終了日=今日(UTC)・直近 30 日。"""
        tenant_id = cp_db.insert_tenant()
        body = client.get(f"{TENANTS}/{tenant_id}/metrics", headers=viewer).json()
        check.equal((body["tenant_id"], body["items"], body["to_date"]), (str(tenant_id), [], TODAY.isoformat()))
        check.equal((TODAY - dt.date.fromisoformat(body["from_date"])).days, 29)

    def test_items_are_ordered_and_values_are_decimal_strings(self, client, viewer, cp_db):
        """日付・指標キーの昇順で、値は 10 進数の文字列。期間外・他テナントの行は含まれない。"""
        tenant_id, other = cp_db.insert_tenant(), cp_db.insert_tenant()
        d1, d2 = TODAY - dt.timedelta(days=3), TODAY - dt.timedelta(days=1)
        insert_metric(cp_db, tenant_id, d2, "users_total", 12)
        insert_metric(cp_db, tenant_id, d1, "users_total", 10)
        insert_metric(cp_db, tenant_id, d1, "users_active", 7)
        insert_metric(cp_db, tenant_id, TODAY - dt.timedelta(days=100), "users_total", 1)
        insert_metric(cp_db, other, d1, "users_total", 999)
        body = client.get(f"{TENANTS}/{tenant_id}/metrics", headers=viewer).json()
        check.equal([(i["date"], i["metric_key"], i["value"]) for i in body["items"]], [(d1.isoformat(), "users_active", "7"), (d1.isoformat(), "users_total", "10"), (d2.isoformat(), "users_total", "12")])
        windowed = client.get(f"{TENANTS}/{tenant_id}/metrics", headers=viewer, params={"from": d2.isoformat(), "to": d2.isoformat()}).json()
        check.equal([i["value"] for i in windowed["items"]], ["12"])

    def test_range_limits(self, client, viewer, cp_db):
        """期間は最大 366 日(両端を含めて 366 日分までは可、367 日分は 422 range_too_long)。開始が終了より後なら 422 invalid_range。"""
        tenant_id = cp_db.insert_tenant()
        path = f"{TENANTS}/{tenant_id}/metrics"
        ok = client.get(path, headers=viewer, params={"from": "2025-12-31", "to": "2026-12-31"})
        check.equal(ok.status_code, 200)
        too_long = client.get(path, headers=viewer, params={"from": "2025-12-30", "to": "2026-12-31"})
        check.equal((too_long.status_code, too_long.json()["errors"][0]["code"]), (422, "range_too_long"))
        reversed_range = client.get(path, headers=viewer, params={"from": "2026-02-01", "to": "2026-01-01"})
        check.equal((reversed_range.status_code, reversed_range.json()["errors"][0]["code"]), (422, "invalid_range"))

    @pytest.mark.parametrize("params", [{"from": "2026/01/01"}, {"to": "yesterday"}, {"from": "2026-13-01"}, {"from": "2026-01-01T10:00:00"}])
    def test_invalid_dates(self, client, viewer, cp_db, params):
        """日付の形式が不正なら 422。"""
        response = client.get(f"{TENANTS}/{cp_db.insert_tenant()}/metrics", headers=viewer, params=params)
        check.equal((response.status_code, response.json()["code"]), (422, "validation_error"))

    def test_unknown_tenant(self, client, viewer):
        """存在しないテナントは 404。"""
        check.equal(client.get(f"{TENANTS}/{uuid.uuid4()}/metrics", headers=viewer).status_code, 404)


class TestMetricsSummary:
    """全テナント合計のサマリー。"""

    def test_status_counts_are_zero_filled(self, client, viewer):
        """tenants_by_status は全状態を 0 埋めで返す。"""
        body = client.get("/api/v1/cp/metrics/summary", headers=viewer).json()
        check.equal(set(body["tenants_by_status"]), {"PROVISIONING", "ACTIVE", "FAILED", "SUSPENDED", "PENDING_DELETION", "DEPROVISIONING", "DELETED"})
        check.is_true(all(isinstance(v, int) and v >= 0 for v in body["tenants_by_status"].values()))

    def test_counts_and_totals_follow_the_data(self, client, viewer, cp_db):
        """テナントの追加と指標の追加が、状態別の件数と指標の合計(最新値・削除済みを除く)に反映される。"""
        before = client.get("/api/v1/cp/metrics/summary", headers=viewer).json()
        total_before = next((m["value"] for m in before["metrics"] if m["metric_key"] == "users_total"), "0")
        live = cp_db.insert_tenant(status="SUSPENDED")
        gone = cp_db.insert_tenant(status="DELETED")
        insert_metric(cp_db, live, TODAY - dt.timedelta(days=2), "users_total", 3)
        insert_metric(cp_db, live, TODAY - dt.timedelta(days=1), "users_total", 8)  # 最新値だけが合計に入る
        insert_metric(cp_db, gone, TODAY, "users_total", 1000)  # 削除済みは除く
        after = client.get("/api/v1/cp/metrics/summary", headers=viewer).json()
        check.equal(after["tenants_by_status"]["SUSPENDED"] - before["tenants_by_status"]["SUSPENDED"], 1)
        check.equal(after["tenants_by_status"]["DELETED"] - before["tenants_by_status"]["DELETED"], 1)
        total_after = next(m["value"] for m in after["metrics"] if m["metric_key"] == "users_total")
        check.equal(int(total_after) - int(total_before), 8)
        check.is_not_none(after["as_of"])
