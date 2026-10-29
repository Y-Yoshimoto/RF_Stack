#!/usr/bin/env python
# coding:utf-8
"""カーソル方式のページネーション（03 §3）。

- リクエスト: ``limit``（既定 50、最大 200）、``cursor``（前回レスポンスの ``next_cursor``）。
- レスポンス: ``{"items": [...], "next_cursor": "..." | null}``。総件数は ``include_total=true`` のときだけ ``total`` に入る。
- カーソルは「並び替えの指定・並び替えキーの値・``id``」を JSON にして base64url にした不透明な文字列。
  クライアントは中身を解釈しない。並び替えの指定が変わったカーソルは 422 とする。

ここは形式（エンコード・デコード・ページの型）だけを持つ。キーセット条件の組み立ては各リポジトリが行う。
"""
import base64
import binascii
import json
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, Field

from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text
from modules.errors.problem import FieldError, ProblemError

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200

# ``limit`` クエリパラメータ。
LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT, description=f"1 ページの件数（既定 {DEFAULT_PAGE_LIMIT}、最大 {MAX_PAGE_LIMIT}）")]
# ``cursor`` クエリパラメータ。
CursorQuery = Annotated[str | None, Query(max_length=1024, description="前回のレスポンスの `next_cursor`。中身は解釈しないこと")]
# ``include_total`` クエリパラメータ。
IncludeTotalQuery = Annotated[bool, Query(description="`true` のとき総件数を `total` に含める")]


class CursorPage[T](BaseModel):
    """カーソル方式の一覧レスポンスの基底（03 §3）。サブクラスで ``items`` の型を指定する。"""

    items: list[T] = Field(description="このページの要素")
    next_cursor: str | None = Field(description="次のページを取得するためのカーソル。最後のページでは `null`")
    total: int | None = Field(default=None, description="絞り込み後の総件数。`include_total=true` のときだけ入る")


def invalid_cursor_error() -> ProblemError:
    """不正なカーソルのエラー（422）を作る（カーソルの中身の検証に失敗したリポジトリ・ルーターも使う）。"""
    return problem_from_text(
        422, "validation_error", text_for_code("validation_error", 422),
        errors=[FieldError(field="cursor", code="invalid_cursor", message="カーソルが正しくありません。先頭から取得し直してください")],
    )


def encode_cursor(payload: dict[str, Any]) -> str:
    """カーソルを作る。

    Args:
        payload: JSON にできる値の dict（並び替えの指定・キーの値・ID）。

    Returns:
        str: base64url（パディング無し）の文字列。
    """
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """カーソルを読む。

    Args:
        cursor: :func:`encode_cursor` が作った文字列。

    Returns:
        dict: カーソルの中身。

    Raises:
        ProblemError(422): 壊れている・形式が違う場合。
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, UnicodeError, ValueError):
        raise invalid_cursor_error() from None
    if not isinstance(payload, dict):
        raise invalid_cursor_error()
    return payload

