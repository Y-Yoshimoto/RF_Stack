# -*- coding: utf-8 -*-
"""テナント分離のテスト用フィクスチャ。

クロステナントテスト(RLS 結合テスト・API テスト)は、本ファイルのフィクスチャを流用する。

提供するフィクスチャ:
    - ``tenant_a`` / ``tenant_b``: 2 テナント分の :class:`TenantContext`
    - ``app_owner_engine`` / ``app_runtime_engine`` / ``app_cp_agent_engine``: ``app_db`` の各ロールのエンジン
      (DB に接続できない・ロールが無い場合はテストをスキップする)
    - ``rls_table_factory``: ``app_owner`` で一時テーブルを作り RLS を適用するファクトリ(終了時に DROP)
    - ``rls_table``: ``tenant_id`` と ``title`` を持つ一時テーブル(RLS 適用済み、空)
    - ``seeded_rls_table``: ``rls_table`` にテナント A が 2 行、テナント B が 1 行入った状態

接続情報は環境変数から読む(``.env`` は読まない)::

    DB_HOST, DB_PORT, APP_DB_NAME,
    APP_DB_OWNER_USER / _PASSWORD, APP_DB_RUNTIME_USER / _PASSWORD, APP_DB_CP_AGENT_USER / _PASSWORD

開発用 DB を壊さないため、テーブル名は実行ごとに一意にし、終了時に必ず DROP する。
"""
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

from modules.tenancy.context import TenantContext, get_tenant_context
from modules.tenancy.db import apply_tenant_guc
from modules.tenancy.rls import build_enable_tenant_rls_sql, quote_identifier


@pytest.fixture(autouse=True)
def _tenant_context_is_clean() -> Iterator[None]:
    """各テストの前後でテナントコンテキストが残っていないことを保証する。"""
    assert get_tenant_context() is None, "前のテストからテナントコンテキストが漏れている"
    yield
    assert get_tenant_context() is None, "テストがテナントコンテキストを元に戻していない"


# ---------------------------------------------------------------------------
# テナント
# ---------------------------------------------------------------------------
@pytest.fixture
def tenant_a() -> TenantContext:
    """テナント A のコンテキスト(user_id 付き)。"""
    return TenantContext(tenant_id=uuid.uuid4(), tenant_code="alpha", user_id=uuid.uuid4(), plane="app")


@pytest.fixture
def tenant_b() -> TenantContext:
    """テナント B のコンテキスト(user_id 付き)。"""
    return TenantContext(tenant_id=uuid.uuid4(), tenant_code="beta", user_id=uuid.uuid4(), plane="app")


# ---------------------------------------------------------------------------
# DB エンジン(app_db)
# ---------------------------------------------------------------------------
def _build_url(user_env: str, password_env: str) -> URL | None:
    """環境変数から接続 URL を組み立てる。必要な変数が欠けていれば ``None``。"""
    values = {name: os.environ.get(name, "") for name in ("DB_HOST", "APP_DB_NAME", user_env, password_env)}
    if not all(values.values()):
        return None
    return URL.create(
        "postgresql",
        username=values[user_env],
        password=values[password_env],
        host=values["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=values["APP_DB_NAME"],
    )


def _connectable_engine(user_env: str, password_env: str, **engine_kwargs: object) -> Engine:
    """接続を確認したエンジンを返す。接続できなければテストをスキップする。

    スキップ理由にパスワードを含めない(例外の文字列表現ではなく型名とロール名だけを出す)。
    """
    url = _build_url(user_env, password_env)
    if url is None:
        pytest.skip(f"DB 接続の環境変数が未設定のためスキップ({user_env} など)")
    engine = create_engine(url, connect_args={"connect_timeout": 3}, **engine_kwargs)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"app_db に {url.username} で接続できないためスキップ(DB 未起動、またはロール未作成)")
    return engine


@pytest.fixture(scope="session")
def app_owner_engine() -> Iterator[Engine]:
    """``app_owner``(テーブル所有者・DDL 用)のエンジン。"""
    engine = _connectable_engine("APP_DB_OWNER_USER", "APP_DB_OWNER_PASSWORD")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_runtime_engine() -> Iterator[Engine]:
    """``app_runtime``(AP の実行時ロール。RLS 適用)のエンジン。"""
    engine = _connectable_engine("APP_DB_RUNTIME_USER", "APP_DB_RUNTIME_PASSWORD")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_cp_agent_engine() -> Iterator[Engine]:
    """``app_cp_agent``(CP からの集計・物理削除用。SELECT/DELETE のみ。RLS 適用)のエンジン。"""
    engine = _connectable_engine("APP_DB_CP_AGENT_USER", "APP_DB_CP_AGENT_PASSWORD")
    yield engine
    engine.dispose()


@pytest.fixture
def single_connection_runtime_engine() -> Iterator[Engine]:
    """プールを 1 接続に固定した ``app_runtime`` のエンジン(接続の再利用を検証する用)。"""
    engine = _connectable_engine("APP_DB_RUNTIME_USER", "APP_DB_RUNTIME_PASSWORD", pool_size=1, max_overflow=0)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# RLS 付き一時テーブル
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RlsTable:
    """テスト用一時テーブルの名前と、よく使う操作のヘルパー。

    テーブルは ``id uuid PK DEFAULT uuidv7()``, ``tenant_id uuid NOT NULL``, ``title text NOT NULL`` を持つ。
    ``schema`` は ``public``。SQL に埋め込む名前は :attr:`qualified` を使う(クォート済み)。
    """

    name: str
    schema: str = "public"

    @property
    def qualified(self) -> str:
        """スキーマ修飾・クォート済みのテーブル名。"""
        return f"{quote_identifier(self.schema)}.{quote_identifier(self.name)}"

    def insert(self, engine: Engine, tenant: TenantContext, title: str) -> None:
        """``tenant`` のコンテキストで 1 行 INSERT してコミットする(RLS の WITH CHECK を通る正しい経路)。"""
        with engine.begin() as connection:
            apply_tenant_guc(connection, tenant.tenant_id)
            connection.execute(text(f"INSERT INTO {self.qualified} (tenant_id, title) VALUES (:tenant_id, :title)"), {"tenant_id": str(tenant.tenant_id), "title": title})

    def titles(self, engine: Engine, tenant: TenantContext | None) -> list[str]:
        """``tenant`` のコンテキストで見える title を昇順で返す(``None`` は GUC 未設定)。"""
        with engine.begin() as connection:
            if tenant is not None:
                apply_tenant_guc(connection, tenant.tenant_id)
            rows = connection.execute(text(f"SELECT title FROM {self.qualified} ORDER BY title")).scalars().all()
        return list(rows)


RlsTableFactory = Callable[..., RlsTable]


@pytest.fixture
def rls_table_factory(app_owner_engine: Engine) -> Iterator[RlsTableFactory]:
    """``app_owner`` で一時テーブルを作成し、``enable_tenant_rls`` 相当を適用するファクトリ。

    使い方::

        def test_x(rls_table_factory):
            table = rls_table_factory()                      # 既定の列(id, tenant_id, title)
            other = rls_table_factory(extra_ddl="note text")  # 追加の列定義

    作成したテーブルはテスト終了時にすべて DROP する。権限は ``app_owner`` の既定権限
    (``app_runtime``: SELECT/INSERT/UPDATE/DELETE、``app_cp_agent``: SELECT/DELETE)で付与される。
    """
    created: list[RlsTable] = []

    def create(*, extra_ddl: str = "", apply_rls: bool = True) -> RlsTable:
        table = RlsTable(name=f"rls_probe_{uuid.uuid4().hex[:12]}")
        columns = ["id uuid PRIMARY KEY DEFAULT uuidv7()", "tenant_id uuid NOT NULL", "title text NOT NULL"]
        if extra_ddl:
            columns.append(extra_ddl)
        with app_owner_engine.begin() as connection:
            connection.execute(text(f"CREATE TABLE {table.qualified} ({', '.join(columns)})"))
            created.append(table)
            if apply_rls:
                for statement in build_enable_tenant_rls_sql(table.name, schema=table.schema):
                    connection.execute(text(statement))
        return table

    try:
        yield create
    finally:
        with app_owner_engine.begin() as connection:
            for table in reversed(created):  # 外部キーの子から先に削除する
                connection.execute(text(f"DROP TABLE IF EXISTS {table.qualified} CASCADE"))


@pytest.fixture
def rls_table(rls_table_factory: RlsTableFactory) -> RlsTable:
    """RLS 適用済みの空の一時テーブル。"""
    return rls_table_factory()


@pytest.fixture
def seeded_rls_table(rls_table: RlsTable, app_runtime_engine: Engine, tenant_a: TenantContext, tenant_b: TenantContext) -> RlsTable:
    """テナント A に 2 行(``a1``, ``a2``)、テナント B に 1 行(``b1``)が入った一時テーブル。"""
    rls_table.insert(app_runtime_engine, tenant_a, "a1")
    rls_table.insert(app_runtime_engine, tenant_a, "a2")
    rls_table.insert(app_runtime_engine, tenant_b, "b1")
    return rls_table
