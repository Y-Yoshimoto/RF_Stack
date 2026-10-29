#!/usr/bin/env python
# coding:utf-8
""" アプリケーションプレーンのテーブルモデルで共有するカラム・制約の部品

    `sa_column` に渡す `Column` は複数のモデルで使い回せないため、関数で毎回生成する。
"""
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, func, text
from sqlmodel import Field

# 論理削除されていない行を表す条件(部分インデックスの WHERE 句。03 §5.1)
NOT_DELETED = "deleted_at IS NULL"


def in_values_check(column: str, values: type[StrEnum], *, name: str | None = None) -> CheckConstraint:
    """
        `column IN ('a', 'b', ...)` の CHECK 制約を返す(列挙値は PostgreSQL の enum ではなく text + CHECK とする)
        column: カラム名
        values: 許可する値の StrEnum(値は定数のみ)
        name: 制約名(命名規約により `<table>_<name>_check` になる。省略時はカラム名)
        return: CheckConstraint
    """
    expression = f"{column} IN ({', '.join(f"'{v.value}'" for v in values)})"
    return CheckConstraint(expression, name=name or column)


def version_positive_check() -> CheckConstraint:
    """ 楽観ロックの `version` が 1 以上であることの CHECK 制約を返す(制約名は `<table>_version_positive_check`) """
    return CheckConstraint("version >= 1", name="version_positive")


def timestamptz_column(*, nullable: bool, server_default: bool = False, onupdate: bool = False) -> Column:
    """
        タイムゾーン付き日時(timestamptz)のカラムを返す
        nullable: NULL を許可するか
        server_default: DB 側の既定値を CURRENT_TIMESTAMP にするか
        onupdate: 更新時に SQLAlchemy 側で現在時刻を設定するか(03 §4: updated_at はアプリ側で更新する)
        return: Column
    """
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=text("CURRENT_TIMESTAMP") if server_default else None,
        onupdate=func.now() if onupdate else None,
    )


def created_at_field(description: str = "作成日時") -> Any:
    """ 作成日時(NOT NULL、既定値 CURRENT_TIMESTAMP)のフィールドを返す """
    return Field(description=description, sa_column=timestamptz_column(nullable=False, server_default=True))


def updated_at_field(description: str = "更新日時") -> Any:
    """ 更新日時(NOT NULL、既定値 CURRENT_TIMESTAMP、更新時に現在時刻)のフィールドを返す """
    return Field(description=description, sa_column=timestamptz_column(nullable=False, server_default=True, onupdate=True))


def deleted_at_field() -> Any:
    """ 論理削除日時(NULL = 有効。03 §5.1)のフィールドを返す """
    return Field(description="削除日時(論理削除。NULL = 有効)", default=None, sa_column=timestamptz_column(nullable=True))


def version_field() -> Any:
    """ 楽観ロック用のバージョン(作成時 1、更新毎に +1。03 §5.2)のフィールドを返す """
    return Field(
        description="楽観ロック用のバージョン(作成時 1、更新毎に +1)",
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")))

