# -*- coding: utf-8 -*-
"""テナント毎のメトリクス(``modules.tenant_metrics``・``AppTenantMetricsRepository``・``metrics_snapshot``)のテスト用フィクスチャ。

- CP の台帳(``control_plane_db``)と AP のデータ(``app_db``)は開発 DB。使い捨てのテナントを作り、終了時に両方を削除する
  (``cp_db`` / ``ap_db``)。alpha / beta には触れない。
- ジョブ全体の実行(``metrics_snapshot``)は、台帳の ACTIVE / SUSPENDED の全テナント(alpha / beta を含む)を対象にするため、
  ``sandbox`` で **外側のトランザクションに載せて最後にロールバック**し、開発 DB の日次メトリクスを書き換えない。
"""
import dataclasses
import datetime as dt
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from ap_services.conftest import ApDb, ap_db, app_cp_agent_engine, app_owner_engine, app_runtime_engine  # noqa: F401
from control_plane.conftest import CpDb, cp_db, cp_owner_engine, cp_runtime_engine  # noqa: F401
from sqlalchemy import Engine, text
from sqlmodel import Session

from control_plane_app.repositories.app_tenant_metrics import AppTenantMetricsRepository
from modules.tenancy.context import TenantContext


@dataclasses.dataclass(frozen=True)
class MetricTenant:
    """台帳と AP の両方に(同じ ID で)使い捨てのテナントを持つ。"""

    id: uuid.UUID
    code: str
    status: str
    ctx: TenantContext


@pytest.fixture
def metric_tenant(cp_db, ap_db) -> Callable[..., MetricTenant]:  # noqa: F811
    """台帳に指定の状態のテナントを作り、同じ ID を AP の後片付けにも登録するファクトリ。"""

    def create(status: str = "ACTIVE") -> MetricTenant:
        requested = dt.datetime.now(dt.UTC) if status in ("PENDING_DELETION", "DEPROVISIONING", "DELETED") else None
        tenant_id = cp_db.insert_tenant(status=status, deletion_requested_at=requested)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        ap_db.track(tenant_id)
        return MetricTenant(id=tenant_id, code=code, status=status, ctx=TenantContext(tenant_id=tenant_id, tenant_code=code, plane="app"))

    return create


@pytest.fixture
def collector(app_cp_agent_engine) -> AppTenantMetricsRepository:  # noqa: F811
    """実際の ``app_cp_agent``(RLS 適用)で集計する、基盤 + 登録済みテーマの指標の集計。"""
    return AppTenantMetricsRepository(engine_factory=lambda: app_cp_agent_engine)


class FakeLock:
    """ジョブの排他ロックの代替(取得できる/できないを選べる)。"""

    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.keys: list[str] = []

    @contextmanager
    def try_acquire(self, key: str) -> Iterator[bool]:
        self.keys.append(key)
        yield self.acquired


@dataclasses.dataclass
class Sandbox:
    """外側のトランザクションに載せた CP DB の接続。ジョブがコミットしても、テスト終了時にロールバックして残さない。"""

    connection: object

    def session(self) -> Session:
        """ジョブに渡すセッション(コミットは SAVEPOINT の解放になり、外側のトランザクションは閉じない)。"""
        return Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def rows(self, sql: str, **params) -> list[dict]:
        return [dict(row) for row in self.connection.execute(text(sql), params).mappings().all()]

    def metrics(self, tenant_id: uuid.UUID) -> dict[tuple[dt.date, str], Decimal]:
        rows = self.rows("SELECT date, metric_key, value FROM t_tenant_daily_metric WHERE tenant_id = :id", id=tenant_id)
        return {(row["date"], row["metric_key"]): row["value"] for row in rows}


@pytest.fixture
def sandbox(cp_db, cp_runtime_engine: Engine) -> Iterator[Sandbox]:  # noqa: F811
    """ロールバックで必ず元に戻る CP DB の接続。``cp_db`` より後に作られ、先に片付く(台帳の削除とロックが競合しない)。"""
    connection = cp_runtime_engine.connect()
    outer = connection.begin()
    try:
        yield Sandbox(connection)
    finally:
        outer.rollback()
        connection.close()
