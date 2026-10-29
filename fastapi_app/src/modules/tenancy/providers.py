#!/usr/bin/env python
# coding:utf-8
"""DB 接続（ロール毎のエンジン・セッション）とテナントレジストリを組み立てるプロバイダ。

ロールと接続先の対応（02 §4.1 / tenant-isolation スキル §2）をここに集約し、
各プレーンのコードはロールを意識せずに用途別の関数を使う。所有者ロール（``cp_owner`` /
``app_owner``）はマイグレーション専用のため、ここでは扱わない。

| 関数 | ロール | DB | 備考 |
| --- | --- | --- | --- |
| :func:`get_cp_registry_reader_engine` | ``cp_registry_reader`` | ``control_plane_db`` | :func:`get_tenant_registry` が使う |
| :func:`get_cp_runtime_engine` | ``cp_runtime`` | ``control_plane_db`` | CP API・定期ジョブ |
| :func:`get_app_runtime_engine` | ``app_runtime`` | ``app_db`` | AP API。RLS 適用 |
| :func:`get_app_cp_agent_engine` | ``app_cp_agent`` | ``app_db`` | CP からの集計・物理削除。RLS 適用 |

遅延生成:
    import 時には環境変数も読まず、DB にも接続しない。各リソースは最初に要求された時点で
    生成し、プロセス内で 1 つを共有する（生成はロックで保護する）。エンジンも最初のクエリまで
    接続しない。環境変数が欠けている場合は、最初の要求時に変数名を含む ``RuntimeError`` になる。

テナント GUC のリスナー:
    :func:`~modules.tenancy.db.install_tenant_guc_listener` は ``app_runtime`` 用の
    ``sessionmaker``（:func:`get_app_sessionmaker`）にだけ登録する。Session クラス全体には登録しない。
    ``app_cp_agent`` は CP が :func:`~modules.tenancy.db.tenant_guc_scope` /
    :func:`~modules.tenancy.db.run_per_tenant` でテナントを明示的に切り替えるため登録しない。

FastAPI での差し替え:
    :func:`get_tenant_registry` / :func:`get_cp_db_session` は ``Depends`` で使い、テストでは
    ``app.dependency_overrides`` で差し替える。``app_runtime`` のセッション依存関数
    （テナントコンテキストの依存関数と組み合わせたもの）は :mod:`modules.tenancy.app_dependency` にある。

後始末:
    アプリケーション終了時（lifespan の終了処理）やテストの後始末では :func:`dispose_providers` を呼ぶ。
"""
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from modules.db_connector.engine import DBConnector

from .context import require_tenant_context
from .db import install_tenant_guc_listener
from .registry import CachedTenantRegistry, SqlTenantRegistry, TenantRegistry

# 全エンジン共通のオプション。
# pool_pre_ping: DB 再起動などで切れた接続をプールから払い出さない。
_ENGINE_OPTIONS = {"pool_pre_ping": True}


class _Lazy[T]:
    """最初の :meth:`get` で生成し、以降は同じ値を返す遅延リソース（スレッド安全）。

    Args:
        factory: 値を生成する関数。
    """

    def __init__(self, factory: Callable[[], T]) -> None:
        """生成関数を保持する（ここでは生成しない）。"""
        self._factory = factory
        self._lock = threading.Lock()
        self._value: T | None = None

    def get(self) -> T:
        """値を返す。未生成なら生成する。

        Returns:
            T: 生成済みの値。
        """
        value = self._value
        if value is not None:
            return value
        with self._lock:
            if self._value is None:
                self._value = self._factory()
            return self._value

    def reset(self) -> T | None:
        """保持している値を破棄し、次回の :meth:`get` で作り直すようにする。

        Returns:
            T | None: 破棄した値（未生成なら ``None``）。後始末は呼び出し側で行う。
        """
        with self._lock:
            value, self._value = self._value, None
        return value


def _engine_from_env(user_env: str, password_env: str, dbname_env: str) -> Callable[[], Engine]:
    """環境変数からエンジンを生成する関数を返す（接続情報は呼び出し時に読む）。

    Args:
        user_env: ユーザー名の環境変数名。
        password_env: パスワードの環境変数名。
        dbname_env: DB 名の環境変数名。

    Returns:
        Callable[[], Engine]: エンジンを生成する関数。
    """

    def factory() -> Engine:
        """:class:`~modules.db_connector.engine.DBConnector` でエンジンを生成する。"""
        return DBConnector.from_env(user_env, password_env, dbname_env, engine_options=_ENGINE_OPTIONS).engine

    return factory


# ---------------------------------------------------------------------------
# エンジン（ロール毎）
# ---------------------------------------------------------------------------
_cp_registry_reader_engine = _Lazy(_engine_from_env("CP_DB_REGISTRY_READER_USER", "CP_DB_REGISTRY_READER_PASSWORD", "CONTROL_PLANE_DB_NAME"))
_cp_runtime_engine = _Lazy(_engine_from_env("CP_DB_RUNTIME_USER", "CP_DB_RUNTIME_PASSWORD", "CONTROL_PLANE_DB_NAME"))
_app_runtime_engine = _Lazy(_engine_from_env("APP_DB_RUNTIME_USER", "APP_DB_RUNTIME_PASSWORD", "APP_DB_NAME"))
_app_cp_agent_engine = _Lazy(_engine_from_env("APP_DB_CP_AGENT_USER", "APP_DB_CP_AGENT_PASSWORD", "APP_DB_NAME"))
_ENGINES = (_cp_registry_reader_engine, _cp_runtime_engine, _app_runtime_engine, _app_cp_agent_engine)


def get_cp_registry_reader_engine() -> Engine:
    """``cp_registry_reader`` で ``control_plane_db`` に接続するエンジン（``v_tenant_registry`` の SELECT のみ）。"""
    return _cp_registry_reader_engine.get()


def get_cp_runtime_engine() -> Engine:
    """``cp_runtime`` で ``control_plane_db`` に接続するエンジン（CP API・定期ジョブ用）。"""
    return _cp_runtime_engine.get()


def get_app_runtime_engine() -> Engine:
    """``app_runtime`` で ``app_db`` に接続するエンジン（AP API 用。RLS 適用）。

    通常はエンジンを直接使わず、:func:`get_app_sessionmaker` / :func:`open_app_session` を使う。
    """
    return _app_runtime_engine.get()


def get_app_cp_agent_engine() -> Engine:
    """``app_cp_agent`` で ``app_db`` に接続するエンジン（CP からの集計・物理削除用。RLS 適用）。

    テナントは :func:`~modules.tenancy.db.tenant_guc_scope` / :func:`~modules.tenancy.db.run_per_tenant`
    で明示的に切り替える。CP のリポジトリ層以外から使わないこと。
    """
    return _app_cp_agent_engine.get()


# ---------------------------------------------------------------------------
# セッション
# ---------------------------------------------------------------------------
def _create_app_sessionmaker() -> sessionmaker[Session]:
    """``app_runtime`` 用の sessionmaker を生成し、テナント GUC のリスナーを登録する。"""
    factory = sessionmaker(bind=get_app_runtime_engine(), class_=Session)
    install_tenant_guc_listener(factory)
    return factory


def _create_cp_sessionmaker() -> sessionmaker[Session]:
    """``cp_runtime`` 用の sessionmaker を生成する（テナント GUC のリスナーは登録しない）。"""
    return sessionmaker(bind=get_cp_runtime_engine(), class_=Session)


_app_sessionmaker = _Lazy(_create_app_sessionmaker)
_cp_sessionmaker = _Lazy(_create_cp_sessionmaker)


def get_app_sessionmaker() -> sessionmaker[Session]:
    """``app_db``（``app_runtime``）用の sessionmaker を返す。

    トランザクション開始時に、その時点のテナントコンテキストを GUC ``app.current_tenant`` に
    設定するリスナーが登録済み。コンテキスト無しで使うと RLS により 0 件になるため、
    通常は :func:`open_app_session`（コンテキスト必須）を使う。
    """
    return _app_sessionmaker.get()


def get_cp_sessionmaker() -> sessionmaker[Session]:
    """``control_plane_db``（``cp_runtime``）用の sessionmaker を返す。"""
    return _cp_sessionmaker.get()


@contextmanager
def open_app_session() -> Iterator[Session]:
    """テナントコンテキスト下で ``app_db`` のセッションを開く（バッチ・CLI でも使える）。

    セッションを開く前にテナントコンテキストを確認し、無ければセッションを開始しない。
    コミットは呼び出し側で行う。ブロックを抜けるとセッションを閉じ、未コミットの変更は破棄される。

    使用例::

        with tenant_scope(TenantContext(tenant_id=tid, tenant_code="acme", plane="app")):
            with open_app_session() as session:
                session.add(todo)
                session.commit()

    Yields:
        Session: ``app_runtime`` のセッション。トランザクション開始時に GUC が自動設定される。

    Raises:
        TenantContextMissingError: テナントコンテキストが設定されていない場合（500 系の想定）。
    """
    require_tenant_context()
    with get_app_sessionmaker()() as session:
        yield session


def get_cp_db_session() -> Iterator[Session]:
    """``control_plane_db``（``cp_runtime``）のセッションを yield する FastAPI 依存関数。

    認証・認可（CP セッションとロールの確認）はルーター側の依存関数で行う。
    コミットはエンドポイント（サービス層）で行う。
    """
    with get_cp_sessionmaker()() as session:
        yield session


CpSessionDep = Annotated[Session, Depends(get_cp_db_session)]


# ---------------------------------------------------------------------------
# テナントレジストリ
# ---------------------------------------------------------------------------
def _create_tenant_registry() -> TenantRegistry:
    """``cp_registry_reader`` のエンジンで ``v_tenant_registry`` を読むキャッシュ付きレジストリを生成する。"""
    return CachedTenantRegistry(SqlTenantRegistry(get_cp_registry_reader_engine()))


_tenant_registry = _Lazy(_create_tenant_registry)


def get_tenant_registry() -> TenantRegistry:
    """プロセス内で共有するテナントレジストリを返す（FastAPI 依存関数としても使える）。

    実体は ``CachedTenantRegistry(SqlTenantRegistry(cp_registry_reader のエンジン))``。
    キャッシュはプロセス内で共有するため、テナントの停止等は最大 TTL（30 秒）遅れて反映される。

    テストでは ``app.dependency_overrides[get_tenant_registry] = lambda: FakeRegistry(...)`` で差し替える。
    """
    return _tenant_registry.get()


TenantRegistryDep = Annotated[TenantRegistry, Depends(get_tenant_registry)]


# ---------------------------------------------------------------------------
# 後始末
# ---------------------------------------------------------------------------
def dispose_providers() -> None:
    """生成済みのレジストリ・sessionmaker・エンジンを破棄する。

    アプリケーション終了時（lifespan の終了処理）やテストの後始末で呼ぶ。
    呼び出し後に各関数を使うと、環境変数を読み直して作り直す。
    """
    _tenant_registry.reset()
    _app_sessionmaker.reset()
    _cp_sessionmaker.reset()
    for lazy_engine in _ENGINES:
        engine = lazy_engine.reset()
        if engine is not None:
            engine.dispose()
