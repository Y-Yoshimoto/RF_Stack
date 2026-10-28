#!/usr/bin/env python
# coding:utf-8
"""AP の一覧のカーソル・並び替えの解釈(03 §3)。

リポジトリは ``(並び替えキーの値, id)`` の組(``Page.next_after``)で返す。ここでそれを不透明なカーソル文字列にし、
受け取ったカーソルを組に戻す。カーソルには並び替えの指定を含め、現在の ``sort`` と違えば 422 にする。
"""
import datetime as dt
import uuid
from collections.abc import Collection
from typing import Any

from main_app.repositories.keyset import ListSort
from modules.api_common.pagination import decode_cursor, encode_cursor, invalid_cursor_error
from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text
from modules.errors.problem import FieldError, ProblemError

# 並び替えキーのうち、日時の列(カーソルでは ISO 8601 の文字列にする)
DATETIME_SORT_KEYS: frozenset[str] = frozenset({"created_at"})


def parse_sort(raw: str, allowed: Collection[str]) -> ListSort:
    """``sort`` クエリを読む。

    Args:
        raw: クエリの値(``display_name`` / ``-created_at`` など)。
        allowed: 許可する並び替えキー。

    Returns:
        ListSort: 並び順。

    Raises:
        ProblemError(422): 許可していないキーの場合。
    """
    try:
        return ListSort.parse(raw, allowed)
    except ValueError:
        keys = ", ".join(allowed)
        error = FieldError(field="sort", code="invalid_sort", message=f"並び替えに使えるキーは {keys} です(先頭に - を付けると降順)")
        raise problem_from_text(422, "validation_error", text_for_code("validation_error", 422), errors=[error]) from None


def encode_next_cursor(sort: ListSort, next_after: tuple[Any, uuid.UUID] | None) -> str | None:
    """次のページの起点をカーソル文字列にする(次が無ければ ``None``)。"""
    if next_after is None:
        return None
    value, last_id = next_after
    return encode_cursor({"s": str(sort), "k": value.isoformat() if isinstance(value, dt.datetime) else value, "i": str(last_id)})


def decode_after(cursor: str | None, sort: ListSort) -> tuple[Any, uuid.UUID] | None:
    """カーソルを読み、キーセットの起点にする。

    Args:
        cursor: 前のページの ``next_cursor``(``None`` なら先頭から)。
        sort: 現在の並び順。

    Returns:
        tuple | None: ``(並び替えキーの値, id)``。

    Raises:
        ProblemError(422): 壊れている、または並び替えの指定が現在の ``sort`` と異なる場合。
    """
    if not cursor:
        return None
    payload = decode_cursor(cursor)
    try:
        if payload["s"] != str(sort):
            raise invalid_cursor_error()
        raw_value = payload["k"]
        if sort.key in DATETIME_SORT_KEYS:
            value: Any = dt.datetime.fromisoformat(raw_value)
            if value.tzinfo is None:
                raise invalid_cursor_error()
        else:
            if not isinstance(raw_value, str):
                raise invalid_cursor_error()
            value = raw_value
        return value, uuid.UUID(str(payload["i"]))
    except ProblemError:
        raise
    except (KeyError, TypeError, ValueError):
        raise invalid_cursor_error() from None
