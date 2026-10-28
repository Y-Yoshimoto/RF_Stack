#!/usr/bin/env python
# coding:utf-8
"""OpenAPI へ Problem Details を反映する（03 §8）。

FastAPI は ``responses={404: {"model": ProblemDetails}}`` を ``application/json`` のレスポンスとして出力し、
422 を ``HTTPValidationError`` で出力する。実際のレスポンスは ``application/problem+json`` の Problem Details
なので、生成した OpenAPI を後処理して次のとおり直す。

- ``ProblemDetails`` を参照するレスポンスの媒体種別を ``application/problem+json`` にする。
- 422 のレスポンスを ``ProblemDetails`` にし、未使用になった ``HTTPValidationError`` / ``ValidationError`` を取り除く。
- ``If-Match`` ヘッダーのパラメータを整える（名前を ``If-Match`` にし、``modules.api_common.etag.require_if_match`` のものは必須にする）。
"""
from typing import Any

from fastapi import FastAPI

from .problem import PROBLEM_MEDIA_TYPE, FieldError, ProblemDetails

_PROBLEM_REF = "#/components/schemas/ProblemDetails"
_JSON_MEDIA_TYPE = "application/json"
# ``modules.api_common.etag.OPENAPI_REQUIRED_MARKER`` と同じ値（api_common が本モジュールに依存するため、循環を避けて値を重複させる）
_REQUIRED_MARKER = "x-required"
_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """エラーレスポンスの OpenAPI 定義（``responses=`` に渡す）を作る。

    Args:
        *status_codes: ドキュメントに載せるステータスコード。

    Returns:
        dict: ``{status: {"model": ProblemDetails, "description": ...}}``。
    """
    descriptions = {
        400: "リクエストが不正",
        401: "未認証・セッション切れ",
        403: "権限なし・テナント停止中・CSRF 検証失敗",
        404: "存在しない、または閲覧権限が無いリソース",
        409: "一意制約違反・状態遷移の不正・実行中の操作との競合",
        412: "楽観ロックの不一致（If-Match が現在のバージョンと異なる）",
        422: "入力検証エラー",
        428: "If-Match ヘッダーが無い",
        429: "レート制限",
        502: "外部依存（IdP 等）の失敗",
        503: "依存するサービス（DB・Redis）を利用できない",
    }
    return {status: {"model": ProblemDetails, "description": descriptions.get(status, "エラー")} for status in status_codes}


def _ensure_problem_schemas(schema: dict[str, Any]) -> None:
    """``components.schemas`` に ``ProblemDetails`` / ``FieldError`` が無ければ追加する。"""
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    if "ProblemDetails" in schemas and "FieldError" in schemas:
        return
    generated = ProblemDetails.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = generated.pop("$defs", {})
    schemas.setdefault("ProblemDetails", generated)
    schemas.setdefault("FieldError", definitions.get("FieldError", FieldError.model_json_schema()))


def _fix_if_match_parameters(operation: dict[str, Any]) -> None:
    """``If-Match`` ヘッダーのパラメータを直す（必須の目印があれば必須にし、``null`` を許す型にしない）。"""
    for parameter in operation.get("parameters", []):
        if parameter.get("in") != "header" or str(parameter.get("name", "")).lower() != "if-match":
            continue
        required = bool(parameter.get("schema", {}).get(_REQUIRED_MARKER, False))
        parameter["name"] = "If-Match"
        parameter["required"] = required
        parameter["schema"] = {"type": "string", "title": "If-Match"}


def _rewrite(schema: dict[str, Any]) -> None:
    """生成済みの OpenAPI を Problem Details 向けに直す（何度呼んでも結果は同じ）。"""
    _ensure_problem_schemas(schema)
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            _fix_if_match_parameters(operation)
            for status, response in operation.get("responses", {}).items():
                content = response.get("content", {})
                if status == "422":
                    response["description"] = "入力検証エラー"
                    response["content"] = {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": _PROBLEM_REF}}}
                elif _JSON_MEDIA_TYPE in content and content[_JSON_MEDIA_TYPE].get("schema", {}).get("$ref") == _PROBLEM_REF:
                    content[PROBLEM_MEDIA_TYPE] = content.pop(_JSON_MEDIA_TYPE)
    schemas = schema["components"]["schemas"]
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)


def install_problem_openapi(app: FastAPI) -> None:
    """``app.openapi()`` の結果を Problem Details 向けに直すようにする。

    Args:
        app: FastAPI アプリ。
    """
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()
        _rewrite(schema)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
