#!/usr/bin/env python
# coding:utf-8
"""リクエスト ID（``X-Request-ID``）の受け取り・生成・保持（03 §1）。

ASGI ミドルウェア :class:`RequestIdMiddleware` が、リクエストヘッダー ``X-Request-ID`` を受け取り
（無い・不正なら生成し）、``contextvars`` と ``scope["state"]["request_id"]`` に保持して、
レスポンスヘッダー ``X-Request-ID`` に付ける。Problem Details の ``request_id``、監査ログ、
（将来の）構造化ログが :func:`get_request_id` で参照する。

``BaseHTTPMiddleware`` は ``contextvars`` の伝播に制約があるため、純粋な ASGI ミドルウェアとして実装している。
"""
import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# 受け付けるリクエスト ID の形式。ログや応答ヘッダーに載せるため、英数字・``-``・``_``・``.`` の 128 文字以内に限る
# （改行などによるヘッダー・ログの汚染を防ぐ）。
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """現在のリクエストのリクエスト ID を返す。

    Returns:
        str | None: リクエスト ID。リクエスト外（バッチ・CLI 等）では ``None``。
    """
    return _request_id_var.get()


def request_id_from_scope(scope: Scope) -> str | None:
    """ASGI の scope からリクエスト ID を取り出す（例外ハンドラ用。ミドルウェア外でも読める）。

    Args:
        scope: ASGI の scope。

    Returns:
        str | None: リクエスト ID。
    """
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    return get_request_id()


def _resolve_request_id(headers: Headers) -> str:
    """ヘッダーのリクエスト ID を検証して採用する。無い・不正なら新しく生成する。"""
    incoming = headers.get(REQUEST_ID_HEADER)
    if incoming is not None and _REQUEST_ID_PATTERN.fullmatch(incoming):
        return incoming
    return str(uuid.uuid7())


class RequestIdMiddleware:
    """リクエスト ID を受け取り（無ければ生成し）、レスポンスヘッダーに付ける ASGI ミドルウェア。

    Args:
        app: 内側の ASGI アプリ。
    """

    def __init__(self, app: ASGIApp) -> None:
        """内側のアプリを保持する。"""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """リクエスト ID を設定して内側のアプリを呼ぶ。終了時は必ず元に戻す。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(Headers(scope=scope))
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = _request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)
