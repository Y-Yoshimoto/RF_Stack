#!/usr/bin/env python
# coding:utf-8
"""一覧のキーセット方式（カーソル）の部品（03 §3）。

並び替えキーと ``id`` の組を行値として比較するため、並び替えキーが重複しても順序が安定する。
カーソルの文字列化（base64url）は API 層が ``modules.api_common.pagination`` で行い、ここでは値の組だけを扱う。
並び替えキーは NOT NULL の列に限る（NULL を含むと行値の比較で行が欠落する）。
"""
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import tuple_
from sqlalchemy.sql import ColumnElement
from sqlmodel.sql.expression import SelectOfScalar

# 一覧の件数の既定値と上限（03 §3。modules.api_common.pagination と同じ値）
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


@dataclass(frozen=True, slots=True)
class ListSort:
    """一覧の並び順。

    Attributes:
        key: 並び替えキー。
        descending: 降順か。``id`` も同じ向きで並べる。
    """

    key: str
    descending: bool = False

    @classmethod
    def parse(cls, raw: str, allowed: Collection[str]) -> "ListSort":
        """``sort`` の値（``name`` / ``-name``）を読む。

        Args:
            raw: ``sort`` の値。
            allowed: 許可する並び替えキー。

        Returns:
            ListSort: 並び順。

        Raises:
            ValueError: 許可していないキーの場合。
        """
        descending = raw.startswith("-")
        key = raw[1:] if descending else raw
        if key not in allowed:
            raise ValueError(f"unsupported sort key: {key}")
        return cls(key=key, descending=descending)

    def __str__(self) -> str:
        """``sort`` と同じ表記にする。"""
        return f"{'-' if self.descending else ''}{self.key}"


@dataclass(frozen=True, slots=True)
class Page[T]:
    """キーセット方式の 1 ページ。

    Attributes:
        items: 要素。
        next_after: 次のページの起点（最後の要素の ``(並び替えキーの値, id)``）。次が無ければ ``None``。
            API 層はこれをカーソル文字列にする。
    """

    items: Sequence[T]
    next_after: tuple[Any, uuid.UUID] | None


def normalize_limit(limit: int) -> int:
    """件数を 1〜:data:`MAX_LIST_LIMIT` に収める。

    Args:
        limit: 指定された件数。

    Returns:
        int: 補正した件数。
    """
    return max(1, min(int(limit), MAX_LIST_LIMIT))


def apply_keyset(statement: SelectOfScalar, sort_column: ColumnElement, id_column: ColumnElement, sort: ListSort, after: tuple[Any, uuid.UUID] | None, limit: int) -> SelectOfScalar:
    """SELECT に、キーセットの起点・並び順・件数（``limit + 1``。次ページの有無の判定用）を付ける。

    Args:
        statement: SELECT 文。
        sort_column: 並び替えの列（NOT NULL）。
        id_column: ``id`` の列。
        sort: 並び順。
        after: 起点（この組より後を返す）。``None`` なら先頭から。
        limit: 件数（補正済み）。

    Returns:
        SelectOfScalar: 条件を付けた SELECT 文。
    """
    if after is not None:
        key = tuple_(sort_column, id_column)
        statement = statement.where(key < tuple_(*after) if sort.descending else key > tuple_(*after))
    if sort.descending:
        statement = statement.order_by(sort_column.desc(), id_column.desc())
    else:
        statement = statement.order_by(sort_column.asc(), id_column.asc())
    return statement.limit(limit + 1)


def build_page[T](rows: Sequence[T], limit: int, sort_key: str) -> Page[T]:
    """``limit + 1`` 件で取得した行からページを作る。

    Args:
        rows: 取得した行（最大 ``limit + 1`` 件）。
        limit: 件数。
        sort_key: 並び替えキー（行の属性名）。

    Returns:
        Page[T]: ページ。
    """
    items = list(rows[:limit])
    if len(rows) <= limit or not items:
        return Page(items=items, next_after=None)
    last = items[-1]
    return Page(items=items, next_after=(getattr(last, sort_key), last.id))
