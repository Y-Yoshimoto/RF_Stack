#!/usr/bin/env python
# coding:utf-8
"""Problem Details の例外ハンドラ（03 §2、02 §5.1）。

:func:`register_exception_handlers` を ``app.py`` から 1 回呼ぶと、次の例外が
``application/problem+json`` に変換される。

| 例外 | 変換 |
| --- | --- |
| :class:`~modules.errors.problem.ProblemError` | そのまま |
| ``HTTPException``（Starlette / FastAPI） | ``detail`` を :mod:`modules.errors.catalog` の表でコードに対応付ける。404（存在しないパス）・405 を含む |
| ``RequestValidationError`` | 422、``errors`` に項目ごとの詳細 |
| ``redis.exceptions.ConnectionError`` / ``TimeoutError``、``sqlalchemy.exc.OperationalError`` | 503（セッションストア・DB に接続できない） |
| その他の ``Exception`` | 500（内容は返さず、ログにスタックトレースを残す） |

サービス層の例外など、プレーン固有の例外は :func:`problem_exception_handler` で変換関数を包んで
``app.add_exception_handler`` に登録する（例: ``control_plane_app.problems``）。

401 / 403 / 404 は AP・CP で同じ形式になる（01 §10.1）。ルーターの違いは ``code`` と ``instance`` にしか現れない。
"""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import redis.exceptions
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .catalog import ProblemText, default_code_for_status, resolve_http_exception_code, text_for_code
from .problem import FieldError, ProblemError, problem_response
from .request_id import request_id_from_scope

logger = logging.getLogger(__name__)

# 入力検証エラーの種類（pydantic の error type）→ 日本語のメッセージ。表に無い種類は汎用のメッセージにする
# （pydantic の英語のメッセージには入力値が含まれうるため、そのまま返さない）。
_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "必須項目です",
    "string_too_short": "短すぎます",
    "string_too_long": "長すぎます",
    "string_pattern_mismatch": "形式が正しくありません",
    "string_type": "文字列で指定してください",
    "int_parsing": "整数で指定してください",
    "int_type": "整数で指定してください",
    "uuid_parsing": "ID の形式が正しくありません",
    "date_parsing": "日付の形式が正しくありません（YYYY-MM-DD）",
    "date_from_datetime_parsing": "日付の形式が正しくありません（YYYY-MM-DD）",
    "date_type": "日付の形式が正しくありません（YYYY-MM-DD）",
    "bool_parsing": "真偽値で指定してください",
    "greater_than": "小さすぎます",
    "greater_than_equal": "小さすぎます",
    "less_than": "大きすぎます",
    "less_than_equal": "大きすぎます",
    "enum": "指定できない値です",
    "literal_error": "指定できない値です",
    "json_invalid": "JSON の形式が正しくありません",
    "model_attributes_type": "オブジェクトで指定してください",
    "extra_forbidden": "指定できない項目です",
}
_GENERIC_VALIDATION_MESSAGE = "値が正しくありません"


def _request_id(request: Request) -> str | None:
    """リクエストのリクエスト ID を返す。"""
    return request_id_from_scope(request.scope)


def respond(request: Request, problem: ProblemError) -> Response:
    """:class:`ProblemError` を ``application/problem+json`` のレスポンスにする。

    Args:
        request: リクエスト（``instance`` とリクエスト ID に使う）。
        problem: エラー。

    Returns:
        Response: Problem Details のレスポンス。
    """
    return problem_response(problem, instance=request.url.path, request_id=_request_id(request))


def problem_from_text(status: int, code: str, text: ProblemText, **kwargs: Any) -> ProblemError:
    """文言の表から :class:`ProblemError` を作る。

    Args:
        status: HTTP ステータス。
        code: エラーコード。
        text: 文言。``text.status`` があればそちらを優先する。
        **kwargs: :class:`ProblemError` の ``errors`` / ``extensions`` / ``headers``。

    Returns:
        ProblemError: エラー。
    """
    return ProblemError(text.status or status, code, text.title, text.detail, **kwargs)


def problem_exception_handler[E: Exception](converter: Callable[[E], ProblemError]) -> Callable[[Request, E], Awaitable[Response]]:
    """例外を :class:`ProblemError` に変換する関数を、FastAPI の例外ハンドラにする。

    5xx に変換した場合は、原因（``__cause__``）を含めてログに残す。

    Args:
        converter: 例外 → :class:`ProblemError` の変換関数（I/O をしない軽い関数）。

    Returns:
        Callable: ``app.add_exception_handler`` に渡せる非同期ハンドラ。
    """

    async def handler(request: Request, exc: E) -> Response:
        problem = converter(exc)
        _log_problem(request, problem, exc)
        return respond(request, problem)

    return handler


def _log_problem(request: Request, problem: ProblemError, exc: BaseException | None) -> None:
    """エラーをログに残す。4xx（利用者の入力・権限）は INFO、5xx は ERROR（03 §6.1）。"""
    if problem.status >= 500:
        logger.error("problem status=%s code=%s method=%s path=%s", problem.status, problem.code, request.method, request.url.path, exc_info=exc)
    else:
        logger.info("problem status=%s code=%s method=%s path=%s", problem.status, problem.code, request.method, request.url.path)


async def _handle_problem_error(request: Request, exc: ProblemError) -> Response:
    """:class:`ProblemError` を変換する。"""
    _log_problem(request, exc, exc if exc.status >= 500 else None)
    return respond(request, exc)


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
    """``HTTPException`` を変換する。``detail`` の文字列はそのまま返さず、表でコードに対応付ける。"""
    code = resolve_http_exception_code(exc.status_code, exc.detail)
    text = text_for_code(code, exc.status_code)
    headers = dict(exc.headers) if exc.headers else None
    problem = problem_from_text(exc.status_code, code, text, headers=headers)
    if code == default_code_for_status(exc.status_code) and isinstance(exc.detail, str) and exc.detail:
        # 表に無い detail は返さない代わりに、調査できるようログに残す（開発中の原因調査用）
        logger.debug("http exception detail (not exposed): status=%s detail=%s", exc.status_code, exc.detail)
    _log_problem(request, problem, None)
    return respond(request, problem)


def _field_name(location: tuple[Any, ...]) -> str:
    """pydantic のエラー位置から項目名を作る（先頭の ``body`` / ``query`` / ``path`` は除く）。"""
    parts = [str(part) for part in location[1:]]
    return ".".join(parts) if parts else str(location[0] if location else "body")


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
    """``RequestValidationError`` を 422 の Problem Details に変換する。"""
    errors = [
        FieldError(
            field=_field_name(tuple(error.get("loc", ()))),
            code=str(error.get("type", "invalid")),
            message=_VALIDATION_MESSAGES.get(str(error.get("type")), _GENERIC_VALIDATION_MESSAGE),
        )
        for error in exc.errors()
    ]
    problem = problem_from_text(422, "validation_error", text_for_code("validation_error", 422), errors=errors)
    _log_problem(request, problem, None)
    return respond(request, problem)


def _service_unavailable(exc: Exception) -> ProblemError:
    """セッションストア・DB に接続できない場合の 503。"""
    return problem_from_text(503, "service_unavailable", text_for_code("service_unavailable", 503), headers={"Retry-After": "5"})


async def _handle_unavailable(request: Request, exc: Exception) -> Response:
    """Redis・DB への接続失敗を 503 にする。"""
    problem = _service_unavailable(exc)
    _log_problem(request, problem, exc)
    return respond(request, problem)


async def _handle_unexpected(request: Request, exc: Exception) -> Response:
    """想定外の例外を 500 にする。内容は返さない。"""
    problem = problem_from_text(500, "internal_error", text_for_code("internal_error", 500))
    _log_problem(request, problem, exc)
    return respond(request, problem)


def register_exception_handlers(app: FastAPI) -> None:
    """共通の例外ハンドラを登録する。

    Args:
        app: FastAPI アプリ。
    """
    app.add_exception_handler(ProblemError, _handle_problem_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(redis.exceptions.ConnectionError, _handle_unavailable)
    app.add_exception_handler(redis.exceptions.TimeoutError, _handle_unavailable)
    app.add_exception_handler(OperationalError, _handle_unavailable)
    app.add_exception_handler(Exception, _handle_unexpected)
