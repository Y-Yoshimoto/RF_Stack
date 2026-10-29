#!/usr/bin/env python
# coding:utf-8
"""API の日時の型（03 §4）。

DB は ``timestamptz``（UTC で保存）だが、ドライバが返す ``tzinfo`` は接続のタイムゾーン設定に依存しうる。
:data:`UtcDatetime` は検証時に UTC へ正規化するため、JSON では常に ``2026-10-27T03:00:00Z`` の形で出力される。
タイムゾーンを持たない値は UTC とみなす。
"""
import datetime as dt
from typing import Annotated

from pydantic import AfterValidator


def to_utc(value: dt.datetime) -> dt.datetime:
    """日時を UTC に正規化する（タイムゾーン無しは UTC とみなす）。

    Args:
        value: 日時。

    Returns:
        datetime: ``tzinfo`` が UTC の日時。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


# スキーマのフィールドに使う、UTC の日時。
UtcDatetime = Annotated[dt.datetime, AfterValidator(to_utc)]
