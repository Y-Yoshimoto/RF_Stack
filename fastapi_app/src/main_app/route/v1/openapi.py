#!/usr/bin/env python
# coding:utf-8
"""AP の成功レスポンスのヘッダー(``ETag`` / ``Location`` / ``Cache-Control``)を OpenAPI に載せる部品。

エラー応答は ``modules.errors.openapi.problem_responses``。``responses=`` には両者を ``{**success_headers(...), **problem_responses(...)}`` で渡す。
"""
from typing import Any

_ETAG = {"description": "リソースのバージョン(`\"<version>\"`)。更新系の `If-Match` にそのまま指定する", "schema": {"type": "string"}}
_LOCATION = {"description": "作成したリソースの URL", "schema": {"type": "string"}}
_NO_STORE = {"description": "`no-store`。一時パスワードを含むためキャッシュさせない", "schema": {"type": "string"}}


def success_headers(status_code: int, description: str, *, etag: bool = True, location: bool = False, no_store: bool = False) -> dict[int | str, dict[str, Any]]:
    """成功レスポンスのヘッダー定義(``responses=`` に渡す)を作る。

    Args:
        status_code: 成功のステータスコード(デコレーターの ``status_code`` と同じ値)。
        description: レスポンスの説明。
        etag: ``ETag`` を返すか。
        location: ``Location`` を返すか。
        no_store: ``Cache-Control: no-store`` を返すか。

    Returns:
        dict: ``{status_code: {"description": ..., "headers": {...}}}``。
    """
    headers: dict[str, Any] = {}
    if etag:
        headers["ETag"] = _ETAG
    if location:
        headers["Location"] = _LOCATION
    if no_store:
        headers["Cache-Control"] = _NO_STORE
    return {status_code: {"description": description, "headers": headers}}
