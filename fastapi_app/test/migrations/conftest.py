# -*- coding: utf-8 -*-
"""Alembic リビジョンのテスト用フィクスチャ(AP DB。使い捨てのスキーマの中で実行する)。

**開発 DB のテーブルに触れない**ための分離:

- ``app_owner`` の接続で 1 本のトランザクションを開き、その中に使い捨てのスキーマ(``zt_mig_<乱数>``)を作って ``search_path`` をそのスキーマだけにする。
  リビジョンのテーブルは修飾なしで作られるため、すべてこのスキーマに作られる。テスト終了時に**ロールバック**するので、何も残らない(DDL もトランザクション内)。
- RLS のヘルパー(``modules.tenancy.rls``)だけは ``public`` を明示するため、SQL を組み立てる関数を差し替えて使い捨てのスキーマを指すようにする
  (差し替えが漏れて ``public`` に対する ``CREATE POLICY`` が走ると、既存のポリシーと衝突して失敗する = 開発 DB を変更しない)。
- リビジョンは ``alembic/app/versions`` のファイルを直接読み込み、``Operations.context`` の下で ``upgrade()`` / ``downgrade()`` を呼ぶ(``env.py`` は使わない)。
"""
import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from ap_services.conftest import app_owner_engine  # noqa: F401
from sqlalchemy import Connection, text

from modules.tenancy import rls

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "app" / "versions"

__all__ = ["Scratch", "app_owner_engine", "scratch"]


class Scratch:
    """使い捨てのスキーマの中でリビジョンを適用する補助。"""

    def __init__(self, connection: Connection, schema: str) -> None:
        self.connection = connection
        self.schema = schema
        self.applied: list[str] = []
        self._modules: dict[str, Any] = {}

    def _load(self, revision: str) -> Any:
        if revision not in self._modules:
            path = next(VERSIONS_DIR.glob(f"{revision}_*.py"))
            spec = importlib.util.spec_from_file_location(f"_zt_migration_{revision}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._modules[revision] = module
        return self._modules[revision]

    def _run(self, func_name: str, revision: str) -> None:
        module = self._load(revision)
        with Operations.context(MigrationContext.configure(self.connection)):
            getattr(module, func_name)()

    def upgrade(self, *revisions: str) -> None:
        """リビジョンを順に ``upgrade()`` する。"""
        for revision in revisions:
            self._run("upgrade", revision)
            self.applied.append(revision)

    def downgrade(self, revision: str) -> None:
        """リビジョンを ``downgrade()`` する(最後に適用したものだけ)。"""
        assert self.applied and self.applied[-1] == revision, f"最後に適用したリビジョンは {self.applied[-1:]}"
        self._run("downgrade", revision)
        self.applied.pop()

    @property
    def revision_module(self) -> Any:
        return self._load

    # -- 参照・準備 -------------------------------------------------------------
    def query(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(text(sql), params).mappings().all()]

    def scalar(self, sql: str, **params: Any) -> Any:
        return self.connection.execute(text(sql), params).scalar_one()

    def exists(self, table: str) -> bool:
        return self.scalar("SELECT to_regclass(:n) IS NOT NULL", n=f"{self.schema}.{table}")

    def columns(self, table: str) -> set[str]:
        return {row["column_name"] for row in self.query("SELECT column_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t", s=self.schema, t=table)}

    def as_tenant(self, tenant_id: uuid.UUID) -> None:
        """以降の SQL をテナントの行として実行する(FORCE RLS のため所有者でも必要。トランザクション内だけ有効)。"""
        self.connection.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": str(tenant_id)})


@pytest.fixture
def scratch(app_owner_engine) -> Iterator[Scratch]:  # noqa: F811
    """使い捨てのスキーマ(リビジョン未適用)。終了時にロールバックする。"""
    schema = f"zt_mig_{uuid.uuid4().hex[:10]}"
    connection = app_owner_engine.connect()
    transaction = connection.begin()
    originals = (rls.build_enable_tenant_rls_sql, rls.build_disable_tenant_rls_sql)
    try:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        # ヘルパーは schema="public" を明示して渡してくるため、受け取った schema を無視して使い捨てのスキーマを指す
        scratch_schema = schema
        rls.build_enable_tenant_rls_sql = lambda table_name, *, schema=None: originals[0](table_name, schema=scratch_schema)
        rls.build_disable_tenant_rls_sql = lambda table_name, *, schema=None: originals[1](table_name, schema=scratch_schema)
        yield Scratch(connection, schema)
    finally:
        rls.build_enable_tenant_rls_sql, rls.build_disable_tenant_rls_sql = originals
        transaction.rollback()
        connection.close()
