#!/usr/bin/env python
# coding:utf-8
"""RFC 9457（Problem Details for HTTP APIs）の例外とレスポンスの組み立て（03 §2）。

エラーは ``Content-Type: application/problem+json`` で次の形に統一する。

.. code-block:: json

    {
      "type": "https://errors.rf-stack.example/tenant-not-found",
      "title": "テナントが見つかりません",
      "status": 404,
      "detail": "指定されたテナントは存在しません",
      "instance": "/api/v1/cp/tenants/0192f0c3-...",
      "code": "tenant_not_found",
      "request_id": "6f1c...",
      "errors": []
    }

- ``code``: 機械判定用の ``snake_case``。フロントはこれで分岐する。
- ``title`` / ``detail``: 利用者向けの日本語。内部情報（SQL・スタックトレース・テナントの存在有無・資格情報）を含めない。
- ``errors``: 入力検証エラーの詳細（``[{field, code, message}]``）。無い場合は空配列。
- 上記以外に、エンドポイント固有の拡張メンバー（例: 払い出し失敗時の ``tenant_id``）を足せる（RFC 9457 §3.2）。

ルーターのコードからは :class:`ProblemError` を送出する。``HTTPException``・``RequestValidationError``・
サービス層の例外の変換は :mod:`modules.errors.handlers` が行う。
"""
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

PROBLEM_MEDIA_TYPE = "application/problem+json"

# ``type`` の基点。解決できる URL でなくてよい（03 §2）。``code`` の ``_`` を ``-`` にして連結する。
PROBLEM_TYPE_BASE_URL = "https://errors.rf-stack.example/"


def problem_type_uri(code: str) -> str:
    """``code`` から ``type`` の URI を機械的に作る。

    Args:
        code: エラーコード（``snake_case``）。

    Returns:
        str: ``https://errors.rf-stack.example/{code を kebab-case にしたもの}``。
    """
    return f"{PROBLEM_TYPE_BASE_URL}{code.replace('_', '-')}"


class FieldError(BaseModel):
    """入力検証エラーの 1 件。"""

    field: str = Field(description="エラーのあった項目（ドット区切り。例: `initial_admin.email`）")
    code: str = Field(description="エラーの種類（`snake_case`。例: `required`, `too_long`）")
    message: str = Field(description="利用者向けのメッセージ（日本語）")


class ProblemDetails(BaseModel):
    """エラーレスポンスの本文（RFC 9457 Problem Details）。OpenAPI のエラー応答のスキーマにも使う。"""

    model_config = {"extra": "allow"}

    type: str = Field(description="エラー種別の URI（`code` から機械的に作る。解決できる URL とは限らない）")
    title: str = Field(description="エラーの短い要約（日本語）")
    status: int = Field(description="HTTP ステータスコード")
    detail: str = Field(description="利用者向けの説明（日本語）。内部情報を含まない")
    instance: str = Field(description="エラーが発生したリクエストのパス")
    code: str = Field(description="機械判定用のエラーコード（`snake_case`）。フロントはこれで分岐する")
    request_id: str | None = Field(default=None, description="リクエスト ID（ログとの突き合わせ用。`X-Request-ID` ヘッダーと同じ）")
    errors: list[FieldError] = Field(default_factory=list, description="入力検証エラーの詳細。無い場合は空配列")


class ProblemError(Exception):
    """Problem Details で返すエラー。ルーター・依存関数から送出する。

    Args:
        status: HTTP ステータスコード。
        code: 機械判定用のエラーコード（``snake_case``）。
        title: 要約（日本語）。
        detail: 説明（日本語）。内部情報を含めない。
        errors: 入力検証エラーの詳細。
        extensions: 拡張メンバー（本文の最上位に足す。標準メンバーと同名のキーは使えない）。
        headers: 追加のレスポンスヘッダー（``Retry-After`` など）。

    Raises:
        ValueError: ``extensions`` が標準メンバーと衝突する場合（定義時の誤り）。
    """

    _RESERVED_MEMBERS = frozenset({"type", "title", "status", "detail", "instance", "code", "request_id", "errors"})

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        *,
        errors: Sequence[FieldError | Mapping[str, str]] | None = None,
        extensions: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """エラーの内容を保持する。"""
        conflicts = self._RESERVED_MEMBERS & set(extensions or {})
        if conflicts:
            raise ValueError(f"extensions must not override standard members: {', '.join(sorted(conflicts))}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = [error if isinstance(error, FieldError) else FieldError(**error) for error in (errors or [])]
        self.extensions = dict(extensions or {})
        self.headers = dict(headers or {})
        super().__init__(f"{status} {code}")


def build_problem_body(problem: ProblemError, *, instance: str, request_id: str | None) -> dict[str, Any]:
    """Problem Details の本文（dict）を組み立てる。

    Args:
        problem: エラー。
        instance: リクエストのパス。
        request_id: リクエスト ID。

    Returns:
        dict[str, Any]: JSON にできる本文。
    """
    body: dict[str, Any] = {
        "type": problem_type_uri(problem.code),
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "instance": instance,
        "code": problem.code,
        "request_id": request_id,
        "errors": [error.model_dump() for error in problem.errors],
    }
    body.update(problem.extensions)
    return body


def problem_response(problem: ProblemError, *, instance: str, request_id: str | None) -> JSONResponse:
    """Problem Details のレスポンスを組み立てる。

    ``X-Request-ID`` ヘッダーも付ける（ミドルウェアの外側で生成されるレスポンス、例えば 500 でも付くように）。

    Args:
        problem: エラー。
        instance: リクエストのパス。
        request_id: リクエスト ID。

    Returns:
        JSONResponse: ``application/problem+json`` のレスポンス。
    """
    headers = dict(problem.headers)
    if request_id:
        headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(
        status_code=problem.status,
        content=build_problem_body(problem, instance=instance, request_id=request_id),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )
