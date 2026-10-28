"""CSRF 対策の依存関数 (docs/architecture/01-platform-concepts.md §7.3、03-conventions.md §1)。

Cookie によるセッションのため、変更系メソッド (POST / PUT / PATCH / DELETE 等) では次の両方を必須とする。

1. カスタムヘッダー ``X-Requested-With: rf-stack``
   同一オリジン構成で CORS を許可しないため、他オリジンのページはこのヘッダーを付けたリクエストを送れない
   (付けるとプリフライトが必要になり、拒否される)。
2. ``Origin`` ヘッダーが許可したオリジン (``FRONTEND_URL`` と ``CSRF_TRUSTED_ORIGINS``) のいずれかと一致すること
   ``Origin`` が無いリクエストも拒否する (ブラウザは変更系メソッドでは同一オリジンでも ``Origin`` を送る)。

Cookie の ``SameSite=Lax`` (``modules.auth.session.set_session_cookie``) と合わせて三重の防御とする。
参照系メソッド (GET / HEAD / OPTIONS / TRACE) は検査しない。参照系で状態を変えないこと。

使い方 (``/api/v1`` などへの適用)::

    from fastapi import APIRouter, Depends
    from modules.auth.csrf import require_csrf_protection

    # ルーター単位: 参照系は素通りするため、ルーター全体に付けてよい
    router = APIRouter(dependencies=[Depends(require_csrf_protection)])

    # アプリ全体に付ける場合
    app.include_router(router_v1, prefix="/api/v1", dependencies=[Depends(require_csrf_protection)])

    # エンドポイント単位
    @router.post("/logout", dependencies=[Depends(require_csrf_protection)])
    def logout(): ...

フロントエンドは変更系の fetch に ``X-Requested-With: rf-stack`` を付ける
(``react_app/src/utils/libs/FetchComponents/common.ts`` の ``generateRequestObject`` が付与する)。

拒否時は 403 (``CSRF validation failed``)。どちらの検査で拒否したかは返さない。
"""
import logging

from fastapi import HTTPException, Request

from .environment import KeyCloakEnvironmentVariables

logger = logging.getLogger(__name__)

CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "rf-stack"

# 検査しないメソッド (RFC 9110 の safe methods)。
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

CSRF_REJECTED_DETAIL = "CSRF validation failed"

# KeyCloak 設定のグローバルインスタンス (FRONTEND_URL を参照する)
_config = KeyCloakEnvironmentVariables()


async def require_csrf_protection(request: Request) -> None:
    """変更系メソッドのリクエストに CSRF 対策のヘッダーがあることを検証する FastAPI Dependency。

    I/O を伴わないため ``async def`` とし、スレッドプールを使わない。

    Args:
        request: リクエスト。

    Raises:
        HTTPException(403): 変更系メソッドで ``X-Requested-With`` が ``rf-stack`` でない、
            または ``Origin`` が無い・許可したオリジンでない場合。
    """
    if request.method.upper() in SAFE_METHODS:
        return

    if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
        logger.warning("csrf rejected: missing or invalid %s (path=%s)", CSRF_HEADER_NAME, request.url.path)
        raise HTTPException(status_code=403, detail=CSRF_REJECTED_DETAIL)

    origin = (request.headers.get("origin") or "").strip().rstrip("/").lower()
    if not origin or origin not in _config.trusted_origins():
        logger.warning("csrf rejected: untrusted origin (path=%s)", request.url.path)
        raise HTTPException(status_code=403, detail=CSRF_REJECTED_DETAIL)
