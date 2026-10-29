# -*- coding: utf-8 -*-
"""SqlTenantRegistry の結合テスト。

本番の ``v_tenant_registry`` はコントロールプレーン DB にあり、app_db のロールからは読めない。
ここでは app_db に同じ列を持つ一時テーブルを作り、``view_name`` に ``public.<table>`` を渡して
SQL(バインド・uuid キャスト・列名)を実 PostgreSQL で確認する。DB が無ければスキップ。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text

from modules.tenancy.registry import SqlTenantRegistry, TenantRecord
from modules.tenancy.rls import quote_identifier


@pytest.fixture
def registry_table(app_owner_engine):
    """v_tenant_registry 相当の一時テーブル(終了時に DROP)。(テーブル名, レコード 2 件)を返す。"""
    name = f"reg_probe_{uuid.uuid4().hex[:12]}"
    records = [
        TenantRecord(uuid.uuid4(), "alpha", "tenant-alpha", "ACTIVE"),
        TenantRecord(uuid.uuid4(), "beta", "tenant-beta", "SUSPENDED"),
    ]
    table = f"public.{quote_identifier(name)}"
    with app_owner_engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {table} (tenant_id uuid PRIMARY KEY, tenant_code text, realm_name text, status text)"))
        connection.execute(text(f"GRANT SELECT ON {table} TO PUBLIC"))
        for r in records:
            connection.execute(text(f"INSERT INTO {table} VALUES (:i, :c, :r, :s)"), {"i": str(r.tenant_id), "c": r.tenant_code, "r": r.realm_name, "s": r.status})
    try:
        yield name, records
    finally:
        with app_owner_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


def test_lookup_by_code_realm_and_id(registry_table, app_runtime_engine):
    """コード・レルム・ID のいずれでも検索でき、UUID に正規化された TenantRecord を返す。"""
    name, (alpha, beta) = registry_table
    registry = SqlTenantRegistry(app_runtime_engine, view_name=f"public.{name}")
    check.equal(registry.get_by_code("alpha"), alpha)
    check.equal(registry.get_by_realm("tenant-beta"), beta)
    check.equal(registry.get_by_id(alpha.tenant_id), alpha)
    check.is_instance(registry.get_by_id(beta.tenant_id).tenant_id, uuid.UUID)


def test_not_found_returns_none(registry_table, app_runtime_engine):
    """該当なしは None(状態では絞り込まない)。"""
    name, _ = registry_table
    registry = SqlTenantRegistry(app_runtime_engine, view_name=f"public.{name}")
    check.is_none(registry.get_by_code("gamma"))
    check.is_none(registry.get_by_realm("tenant-gamma"))
    check.is_none(registry.get_by_id(uuid.uuid4()))


def test_values_are_bound_not_interpolated(registry_table, app_runtime_engine):
    """値はバインドされるため、SQL 断片を渡しても全件ヒットせず None になる。"""
    name, _ = registry_table
    registry = SqlTenantRegistry(app_runtime_engine, view_name=f"public.{name}")
    check.is_none(registry.get_by_code("alpha' OR '1'='1"))
    check.is_none(registry.get_by_realm("x' OR 1=1 --"))
