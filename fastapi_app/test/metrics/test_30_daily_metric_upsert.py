# -*- coding: utf-8 -*-
"""control_plane_app.repositories.daily_metric_repository.upsert_daily_metrics(日次メトリクスの UPSERT。01 CP-MET-05)のテスト。

開発 DB の ``control_plane_db`` に、使い捨てのテナントの行を作る(``cp_db`` が終了時に削除する)。
``updated_at`` はトランザクション開始時刻になるため、更新の有無はコミットを分けて確認する。
"""
import datetime as dt
from decimal import Decimal

import pytest
import pytest_check as check
from sqlalchemy import text

from control_plane_app.repositories.daily_metric_repository import upsert_daily_metrics

DAY = dt.date(2026, 5, 1)
NEXT_DAY = dt.date(2026, 5, 2)


def upsert(cp_db, tenant_id, date, values) -> int:
    """1 回の UPSERT をコミットし、変更した行数を返す。"""
    with cp_db.session() as session:
        changed = upsert_daily_metrics(session, tenant_id, date, {key: Decimal(value) for key, value in values.items()})
        session.commit()
    return changed


def rows(cp_db, tenant_id) -> dict[tuple[dt.date, str], dict]:
    with cp_db.runtime.connect() as connection:
        result = connection.execute(text("SELECT * FROM t_tenant_daily_metric WHERE tenant_id = :id"), {"id": tenant_id}).mappings().all()
    return {(row["date"], row["metric_key"]): dict(row) for row in result}


@pytest.fixture
def tenant_id(cp_db):
    return cp_db.insert_tenant()


def test_inserts_one_row_per_key(cp_db, tenant_id):
    """指標ごとに 1 行を追加し、変更した行数を返す。値は numeric(Decimal)のまま保存する。"""
    changed = upsert(cp_db, tenant_id, DAY, {"users_total": 5, "todo_count": "7.50"})
    check.equal(changed, 2)
    saved = rows(cp_db, tenant_id)
    check.equal({key: row["value"] for key, row in saved.items()}, {(DAY, "users_total"): Decimal(5), (DAY, "todo_count"): Decimal("7.50")})


def test_same_values_do_not_change_rows_or_updated_at(cp_db, tenant_id):
    """同じ日に同じ値で再実行しても、行数は増えず、変更行数は 0 で、updated_at も変わらない(値が同じなら更新しない)。"""
    upsert(cp_db, tenant_id, DAY, {"users_total": 5, "todo_count": 7})
    first = rows(cp_db, tenant_id)
    changed = upsert(cp_db, tenant_id, DAY, {"users_total": 5, "todo_count": 7})
    second = rows(cp_db, tenant_id)
    check.equal(changed, 0)
    check.equal(len(second), 2)
    check.equal({k: v["updated_at"] for k, v in second.items()}, {k: v["updated_at"] for k, v in first.items()})
    check.equal({k: v["created_at"] for k, v in second.items()}, {k: v["created_at"] for k, v in first.items()})


def test_changed_value_overwrites_only_that_row(cp_db, tenant_id):
    """値が変わった行だけを上書きして updated_at を進める。変わらない行の updated_at は保たれる。行数は増えない。"""
    upsert(cp_db, tenant_id, DAY, {"users_total": 5, "todo_count": 7})
    first = rows(cp_db, tenant_id)
    changed = upsert(cp_db, tenant_id, DAY, {"users_total": 6, "todo_count": 7})
    second = rows(cp_db, tenant_id)
    check.equal(changed, 1)
    check.equal(len(second), 2)
    check.equal(second[(DAY, "users_total")]["value"], Decimal(6))
    check.greater(second[(DAY, "users_total")]["updated_at"], first[(DAY, "users_total")]["updated_at"])
    check.equal(second[(DAY, "todo_count")]["updated_at"], first[(DAY, "todo_count")]["updated_at"])


def test_decimal_scale_difference_is_not_a_change(cp_db, tenant_id):
    """数値として等しい値(7 と 7.00)は変更とみなさない。"""
    upsert(cp_db, tenant_id, DAY, {"todo_count": "7"})
    check.equal(upsert(cp_db, tenant_id, DAY, {"todo_count": "7.00"}), 0)


def test_other_dates_and_tenants_are_independent(cp_db, tenant_id):
    """別の日は別の行(推移として残る)。別のテナントの行は変わらない。"""
    other = cp_db.insert_tenant()
    upsert(cp_db, tenant_id, DAY, {"users_total": 1})
    upsert(cp_db, other, DAY, {"users_total": 100})
    check.equal(upsert(cp_db, tenant_id, NEXT_DAY, {"users_total": 2}), 1)
    check.equal({k: v["value"] for k, v in rows(cp_db, tenant_id).items()}, {(DAY, "users_total"): Decimal(1), (NEXT_DAY, "users_total"): Decimal(2)})
    check.equal({k: v["value"] for k, v in rows(cp_db, other).items()}, {(DAY, "users_total"): Decimal(100)})


def test_empty_values_do_nothing(cp_db, tenant_id):
    """値が空なら何もしない(0 を返す)。"""
    check.equal(upsert(cp_db, tenant_id, DAY, {}), 0)
    check.equal(rows(cp_db, tenant_id), {})


def test_zero_is_stored(cp_db, tenant_id):
    """0 は有効な値として保存する(集計前の「行なし」と区別できる)。"""
    check.equal(upsert(cp_db, tenant_id, DAY, {"todo_count": 0}), 1)
    check.equal(rows(cp_db, tenant_id)[(DAY, "todo_count")]["value"], Decimal(0))
    check.equal(upsert(cp_db, tenant_id, DAY, {"todo_count": 0}), 0)


def test_repeated_upserts_leave_one_row_per_key(cp_db, tenant_id):
    """同じ (テナント, 日, 指標) への UPSERT を続けて行っても 1 行のまま(一意制約による ON CONFLICT)。"""
    for value in (1, 2, 3, 3, 2):
        upsert(cp_db, tenant_id, DAY, {"todo_count": value})
    saved = rows(cp_db, tenant_id)
    check.equal(len(saved), 1)
    check.equal(saved[(DAY, "todo_count")]["value"], Decimal(2))
