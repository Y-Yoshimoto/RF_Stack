#!/usr/bin/env python
# coding:utf-8
"""``ETag`` / ``If-Match`` による楽観ロック（03 §5.2）。

- ``GET`` は ``ETag: "<version>"`` を返す（:func:`format_etag`）。
- 更新系は ``If-Match: "<version>"`` を必須とする。ヘッダー無しは 428、不一致は 412（不一致の判定はサービス層）。
  :data:`IfMatchVersion` 依存関数がヘッダーを検証して ``version``（整数）を渡す。

使用例::

    @router.post("/{tenant_id}/suspend")
    def suspend_tenant(tenant_id: uuid.UUID, version: IfMatchVersion, response: Response) -> TenantRead:
        view = service.suspend(tenant_id, expected_version=version, ...)
        set_etag(response, view.version)
"""
import re
from typing import Annotated

from fastapi import Depends, Header, Response

from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text
from modules.errors.problem import ProblemError

ETAG_HEADER = "ETag"

# ``"3"`` または弱い検証子 ``W/"3"``。バージョンは 1 以上の整数。
_IF_MATCH_PATTERN = re.compile(r'(?:W/)?"(?P<version>[1-9][0-9]{0,17})"')


def format_etag(version: int) -> str:
    """バージョンから ``ETag`` の値を作る。

    Args:
        version: 楽観ロックのバージョン。

    Returns:
        str: ``"<version>"``（二重引用符を含む）。
    """
    return f'"{version}"'


def set_etag(response: Response, version: int) -> None:
    """レスポンスに ``ETag`` ヘッダーを付ける。

    Args:
        response: レスポンス。
        version: 楽観ロックのバージョン。
    """
    response.headers[ETAG_HEADER] = format_etag(version)


def parse_if_match(value: str | None) -> int:
    """``If-Match`` ヘッダーの値をバージョンにする。

    Args:
        value: ヘッダーの値。

    Returns:
        int: バージョン。

    Raises:
        ProblemError(428): ヘッダーが無い。
        ProblemError(400): 形式が不正（``"<整数>"`` 以外。``*`` や複数指定を含む）。
    """
    if value is None or not value.strip():
        raise problem_from_text(428, "precondition_required", text_for_code("precondition_required", 428))
    match = _IF_MATCH_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ProblemError(400, "invalid_if_match", "If-Match ヘッダーが不正です", 'If-Match には、取得した ETag の値（例: "3"）をそのまま指定してください')
    return int(match.group("version"))


# OpenAPI で必須のヘッダーとして出すための目印(``modules.errors.openapi`` が必須に直して取り除く)。
# ヘッダーが無い場合は 422 ではなく 428 を返したいため、FastAPI 上は任意のパラメータとして宣言している。
OPENAPI_REQUIRED_MARKER = "x-required"


def require_if_match(
    if_match: Annotated[str | None, Header(description='取得した ETag（例: `"3"`）。必須(無ければ 428)。更新対象のバージョンと一致しない場合は 412', json_schema_extra={OPENAPI_REQUIRED_MARKER: True})] = None,
) -> int:
    """``If-Match`` ヘッダーを必須としてバージョンを返す FastAPI 依存関数。"""
    return parse_if_match(if_match)


def optional_if_match(if_match: Annotated[str | None, Header(description='取得した ETag（例: `"3"`）。指定した場合は更新対象のバージョンと一致しないと 412')] = None) -> int | None:
    """``If-Match`` ヘッダーを任意としてバージョンを返す FastAPI 依存関数（無ければ ``None``）。"""
    if if_match is None:
        return None
    return parse_if_match(if_match)


# 必須の ``If-Match``（バージョン）。
IfMatchVersion = Annotated[int, Depends(require_if_match)]
# 任意の ``If-Match``（バージョン。無ければ ``None``）。
OptionalIfMatchVersion = Annotated[int | None, Depends(optional_if_match)]
