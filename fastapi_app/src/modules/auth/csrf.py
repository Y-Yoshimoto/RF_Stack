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

OpenAPI:
    ``X-Requested-With`` は依存関数の ``Header`` 引数として宣言しているため、依存関数を付けたエンドポイントの
    パラメータに現れる。:func:`install_csrf_openapi` が生成後の OpenAPI を直し、変更系メソッドでは必須
    (値は ``rf-stack`` のみ)、参照系メソッドでは載せない (検査しないため)。``Origin`` はブラウザが付ける
    ヘッダーであり、クライアントのコードからは設定できないためパラメータには載せず、説明文にだけ書く。
"""
import logging
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request

from .environment import KeyCloakEnvironmentVariables

logger = logging.getLogger(__name__)

CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "rf-stack"

# 検査しないメソッド (RFC 9110 の safe methods)。
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

CSRF_REJECTED_DETAIL = "CSRF validation failed"

# KeyCloak 設定のグローバルインスタンス (FRONTEND_URL を参照する)
_config = KeyCloakEnvironmentVariables()


CSRF_HEADER_DESCRIPTION = (
    f"CSRF 対策のカスタムヘッダー。状態を変える操作(POST / PUT / PATCH / DELETE)では `{CSRF_HEADER_VALUE}` が必須。"
    "あわせてブラウザが付ける `Origin` が許可したオリジンと一致する必要がある。不足・不一致は 403(`csrf_validation_failed`)"
)


async def require_csrf_protection(
    request: Request,
    x_requested_with: Annotated[str | None, Header(alias=CSRF_HEADER_NAME, description=CSRF_HEADER_DESCRIPTION)] = None,
) -> None:
    """変更系メソッドのリクエストに CSRF 対策のヘッダーがあることを検証する FastAPI Dependency。

    I/O を伴わないため ``async def`` とし、スレッドプールを使わない。

    Args:
        request: リクエスト (メソッドと ``Origin`` を参照する)。
        x_requested_with: ``X-Requested-With`` ヘッダーの値 (複数ある場合は先頭)。

    Raises:
        HTTPException(403): 変更系メソッドで ``X-Requested-With`` が ``rf-stack`` でない、
            または ``Origin`` が無い・許可したオリジンでない場合。
    """
    if request.method.upper() in SAFE_METHODS:
        return

    if x_requested_with != CSRF_HEADER_VALUE:
        logger.warning("csrf rejected: missing or invalid %s (path=%s)", CSRF_HEADER_NAME, request.url.path)
        raise HTTPException(status_code=403, detail=CSRF_REJECTED_DETAIL)

    origin = (request.headers.get("origin") or "").strip().rstrip("/").lower()
    if not origin or origin not in _config.trusted_origins():
        logger.warning("csrf rejected: untrusted origin (path=%s)", request.url.path)
        raise HTTPException(status_code=403, detail=CSRF_REJECTED_DETAIL)


# ------------------------------------------------------------------ OpenAPI

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _is_csrf_header(parameter: dict[str, Any]) -> bool:
    """OpenAPI のパラメータが ``X-Requested-With`` ヘッダーかどうかを返す。"""
    return parameter.get("in") == "header" and str(parameter.get("name", "")).lower() == CSRF_HEADER_NAME.lower()


def _rewrite_csrf_parameters(schema: dict[str, Any]) -> None:
    """生成済みの OpenAPI の ``X-Requested-With`` を直す (何度呼んでも結果は同じ)。

    - 参照系メソッド: パラメータから取り除く (検査しないため)。
    - 変更系メソッド: 必須にし、値を ``rf-stack`` に限る。
    - 入力が CSRF のヘッダーだけの操作からは、FastAPI がパラメータの存在だけを理由に付ける 422 を取り除く
      (ヘッダーは任意の文字列を受け付け、不足・不一致は 422 ではなく 403 になるため)。
    """
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or "parameters" not in operation:
                continue
            parameters = operation["parameters"]
            if not any(_is_csrf_header(parameter) for parameter in parameters):
                continue
            if method.upper() in SAFE_METHODS:
                parameters = [parameter for parameter in parameters if not _is_csrf_header(parameter)]
            else:
                for parameter in parameters:
                    if _is_csrf_header(parameter):
                        parameter["required"] = True
                        parameter["schema"] = {"type": "string", "enum": [CSRF_HEADER_VALUE], "title": CSRF_HEADER_NAME}
            if parameters:
                operation["parameters"] = parameters
            else:
                del operation["parameters"]
            if "requestBody" not in operation and all(_is_csrf_header(parameter) for parameter in parameters):
                operation.get("responses", {}).pop("422", None)


def install_csrf_openapi(app: FastAPI) -> None:
    """``app.openapi()`` の結果の ``X-Requested-With`` を、変更系メソッドだけの必須ヘッダーに直すようにする。

    Args:
        app: FastAPI アプリ。
    """
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()
        _rewrite_csrf_parameters(schema)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
