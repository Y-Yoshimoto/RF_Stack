#!/usr/bin/env python
# coding:utf-8
"""CP DB の advisory lock による排他（同一テナントの払い出し・削除の同時実行防止、定期ジョブの二重実行防止）。

01 CP-ONB-07 / §12.1、02 §5.5。

``PROVISIONING`` の記録は外部呼び出しの前にコミットするため（01 CP-ONB-08）、払い出し全体を 1 つの
トランザクションの行ロックで囲めない。そこで、払い出し用の Session とは **別の接続** でセッションレベルの
advisory lock（``pg_try_advisory_lock(hashtext(key))``）を取得し、処理が終わるまで保持する。
プロセスが落ちて接続が切れればロックも解放されるため、「ロックが取れる = 実行中の処理は無い」と判断できる。
"""
import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

_TRY_LOCK_SQL = text("SELECT pg_try_advisory_lock(hashtext(:key))")
_UNLOCK_SQL = text("SELECT pg_advisory_unlock(hashtext(:key))")


def tenant_lock_key(tenant_code: str) -> str:
    """テナント単位の操作（払い出し・再実行・物理削除・中断の回収）のロックキーを返す。

    Args:
        tenant_code: テナントコード。

    Returns:
        str: ロックキー。
    """
    return f"cp:tenant:{tenant_code}"


class OperationLock(Protocol):
    """キー単位の排他ロック（取得できなければ待たずに諦める）。テストではフェイクに差し替える。"""

    def try_acquire(self, key: str) -> AbstractContextManager[bool]:
        """ロックの取得を試み、ブロックの間保持する。

        Args:
            key: ロックキー。

        Returns:
            AbstractContextManager[bool]: 取得できたかどうかを返すコンテキストマネージャ。
                ブロックを抜けると解放する。
        """
        ...


class PgAdvisoryLock:
    """PostgreSQL のセッションレベル advisory lock による :class:`OperationLock` の実装。

    ロック専用の接続をエンジンから取り出し、ブロックの間保持する（接続プールの 1 本を占有する）。

    Args:
        engine: CP DB のエンジン（``cp_runtime``）。
    """

    def __init__(self, engine: Engine) -> None:
        """エンジンを保持する（ここでは接続しない）。"""
        self._engine = engine

    @contextmanager
    def try_acquire(self, key: str) -> Iterator[bool]:
        """advisory lock の取得を試み、ブロックの間保持する。

        取得後すぐに暗黙のトランザクションを閉じ、接続を idle in transaction にしない
        （セッションレベルのロックはトランザクションを閉じても保持される）。
        解放に失敗した接続はプールに戻さず破棄する（ロックを持ったままプールに戻るのを防ぐ）。

        Args:
            key: ロックキー。

        Yields:
            bool: 取得できたかどうか。
        """
        with self._engine.connect() as connection:
            acquired = bool(connection.execute(_TRY_LOCK_SQL, {"key": key}).scalar())
            connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    try:
                        connection.execute(_UNLOCK_SQL, {"key": key})
                        connection.commit()
                    except Exception:
                        logger.warning("advisory lock の解放に失敗したため接続を破棄します", exc_info=True)
                        connection.invalidate()
