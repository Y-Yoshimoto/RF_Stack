#!/usr/bin/env python
# coding:utf-8
"""テナントコンテキストの保持を担うモジュール（フレームワーク非依存）。

リクエストやバッチ処理が「どのテナントとして動いているか」を
:class:`TenantContext` として表現し、``contextvars`` で実行コンテキストに紐づけて保持する。
ロガーや DB 層（:mod:`modules.tenancy.db`）は :func:`get_tenant_context` で参照する。

設計方針:
    - テナントコンテキストは **認証済みセッションからのみ導出** する。リクエストボディや
      クエリの ``tenant_id`` から組み立ててはならない（組み立ては
      :mod:`modules.tenancy.resolver` が担う）。
    - ``contextvars`` はスレッド・asyncio タスクごとに独立しているため、
      並行リクエスト間でテナントが混ざらない。
    - 設定と解除は必ず ``Token`` を使って対で行う。:func:`tenant_scope` を使えば
      例外時も確実に元の値へ戻る。

使用例::

    from modules.tenancy.context import TenantContext, tenant_scope

    with tenant_scope(TenantContext(tenant_id=tid, tenant_code="acme", plane="cp")):
        do_something()  # この中では require_tenant_context() が値を返す
"""
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

# テナントコンテキストを利用するプレーン。
#   app: アプリケーションプレーン（テナント利用者のリクエスト）
#   cp:  コントロールプレーン（集計・削除などテナント横断の運用処理）
Plane = Literal["app", "cp"]


class TenantContextMissingError(RuntimeError):
    """テナントコンテキストが必要な処理で、コンテキストが設定されていない場合の例外。

    テナント分離の前提が崩れているプログラミングエラーを示す。HTTP の 4xx として
    クライアントに返すものではなく、500 系として扱う想定。
    """


@dataclass(frozen=True, slots=True)
class TenantContext:
    """現在の処理が属するテナントを表す不変オブジェクト。

    Attributes:
        tenant_id: テナント ID（UUID）。RLS の GUC ``app.current_tenant`` に設定される値。
        tenant_code: テナントコード。ログやメトリクスでの識別用。
        user_id: 認証主体の ID（Keycloak の ``sub``）。UUID として解釈できない場合や、
            コントロールプレーンのシステム処理では ``None``。
        plane: コンテキストを生成したプレーン（``"app"`` / ``"cp"``）。

    Raises:
        TypeError: ``tenant_id`` / ``user_id`` が ``uuid.UUID`` でない場合。文字列を
            そのまま渡して型の取り違えに気づかない事故を防ぐため、生成時に検証する。
        ValueError: ``tenant_code`` が空、または ``plane`` が未定義の値の場合。
    """

    tenant_id: uuid.UUID
    tenant_code: str
    user_id: uuid.UUID | None = None
    plane: Plane = "app"

    def __post_init__(self) -> None:
        """フィールドの型と値を検証する。"""
        if not isinstance(self.tenant_id, uuid.UUID):
            raise TypeError("tenant_id must be uuid.UUID")
        if self.user_id is not None and not isinstance(self.user_id, uuid.UUID):
            raise TypeError("user_id must be uuid.UUID or None")
        if not self.tenant_code:
            raise ValueError("tenant_code must not be empty")
        if self.plane not in ("app", "cp"):
            raise ValueError("plane must be 'app' or 'cp'")


# 現在のテナントコンテキスト。未設定時は None。
_current_tenant: ContextVar[TenantContext | None] = ContextVar("current_tenant", default=None)


def get_tenant_context() -> TenantContext | None:
    """現在のテナントコンテキストを取得する。

    Returns:
        TenantContext | None: 設定されていればそのコンテキスト。未設定なら ``None``。
    """
    return _current_tenant.get()


def require_tenant_context() -> TenantContext:
    """現在のテナントコンテキストを取得する。未設定の場合は例外とする。

    テナントに属するデータを扱う処理の入口で呼び、コンテキストの設定漏れを早期に検知する。

    Returns:
        TenantContext: 現在のテナントコンテキスト。

    Raises:
        TenantContextMissingError: テナントコンテキストが設定されていない場合。
    """
    ctx = _current_tenant.get()
    if ctx is None:
        raise TenantContextMissingError("tenant context is not set")
    return ctx


def set_tenant_context(ctx: TenantContext | None) -> Token[TenantContext | None]:
    """テナントコンテキストを設定し、復元用の ``Token`` を返す（低レベル API）。

    通常は :func:`tenant_scope` を使う。本関数を直接使う場合は、必ず
    :func:`reset_tenant_context` と ``try`` / ``finally`` で対にすること。

    Args:
        ctx: 設定するテナントコンテキスト。``None`` で明示的に未設定状態にする。

    Returns:
        Token: :func:`reset_tenant_context` に渡す復元用トークン。
    """
    return _current_tenant.set(ctx)


def reset_tenant_context(token: Token[TenantContext | None]) -> None:
    """:func:`set_tenant_context` の直前の状態に戻す（低レベル API）。

    Args:
        token: :func:`set_tenant_context` が返したトークン。

    Raises:
        ValueError: トークンが別の ``Context`` で生成された場合（``ContextVar.reset`` の仕様）。
        RuntimeError: 同じトークンで 2 回以上復元した場合（``ContextVar.reset`` の仕様）。
    """
    _current_tenant.reset(token)


@contextmanager
def tenant_scope(ctx: TenantContext | None) -> Iterator[TenantContext | None]:
    """ブロック内だけテナントコンテキストを設定するコンテキストマネージャ。

    終了時（例外発生時を含む）には ``Token`` によって直前の値へ確実に戻す。
    入れ子にした場合も、内側を抜けると外側のコンテキストに戻る。

    Args:
        ctx: ブロック内で有効にするテナントコンテキスト。``None`` を渡すと
            ブロック内を明示的に「テナントなし」にできる。

    Yields:
        TenantContext | None: 設定したコンテキスト（``ctx`` そのもの）。
    """
    token = _current_tenant.set(ctx)
    try:
        yield ctx
    finally:
        _current_tenant.reset(token)
