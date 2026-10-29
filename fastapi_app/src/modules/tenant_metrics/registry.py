#!/usr/bin/env python
# coding:utf-8
"""テーマ固有指標の登録箇所（01 §13 #5 の拡張点。CP-MET-02）。

テーマは指標セット（:class:`~modules.tenant_metrics.definition.TenantMetricSet`）を **テーマ側のモジュール**
（``main_app`` 配下）に定義し、:data:`THEME_METRIC_SOURCES` に ``"<モジュール>:<属性>"`` を 1 行追加する。
登録はここだけで行う。

``control_plane_app`` は ``main_app`` を import しない（02 §5.1）ため、CP の集計処理はテーマのモジュールを
直接 import せず、:func:`load_theme_metric_sets` で文字列から読み込む。属性は ``TenantMetricSet`` 1 つ、
またはその列（tuple / list）とする。

基盤の指標（``users_total`` / ``users_active``。CP-MET-01）はここには登録しない
（``control_plane_app/repositories/app_tenant_metrics.py`` が持つ）。キーが基盤の指標と重複すると集計時にエラーになる。

例（ToDo）::

    # main_app/repositories/todos/metrics.py
    TODO_METRICS = TenantMetricSet(name="todo", keys=("todo_count", ...), collect=collect_todo_metrics, primary_keys=("todo_count",))

    # 本モジュール
    THEME_METRIC_SOURCES = ("main_app.repositories.todos.metrics:TODO_METRICS",)
"""
import importlib
from collections.abc import Iterable

from .definition import TenantMetricSet, validate_metric_sets

# テーマ固有指標の提供元（"<モジュール>:<属性>"）。テーマを追加・差し替えるときはここだけを編集する。
THEME_METRIC_SOURCES: tuple[str, ...] = (
    # ToDo（docs/spec/ToDoApp.md §7 #5）
    "main_app.repositories.todos.metrics:TODO_METRICS",
)


def _load_source(source: str) -> list[TenantMetricSet]:
    """``"<モジュール>:<属性>"`` を読み込み、指標セットの一覧を返す。

    Args:
        source: 提供元。

    Returns:
        list[TenantMetricSet]: 指標セット。

    Raises:
        ValueError: 形式が不正、または属性が指標セットでない場合。
        ImportError: モジュールを読み込めない場合。
    """
    module_name, sep, attr = source.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"invalid theme metric source (expected '<module>:<attribute>'): {source!r}")
    value = getattr(importlib.import_module(module_name), attr)
    items = list(value) if isinstance(value, tuple | list) else [value]
    if not all(isinstance(item, TenantMetricSet) for item in items):
        raise ValueError(f"theme metric source {source!r} must be TenantMetricSet or a sequence of them")
    return items


def load_theme_metric_sets(sources: Iterable[str] = THEME_METRIC_SOURCES) -> tuple[TenantMetricSet, ...]:
    """登録されたテーマ固有の指標セットを読み込む。

    Args:
        sources: 提供元（省略時は :data:`THEME_METRIC_SOURCES`）。

    Returns:
        tuple[TenantMetricSet, ...]: 指標セット（登録順）。

    Raises:
        ValueError: 提供元の形式・型が不正、または指標キーが重複する場合。
        ImportError: モジュールを読み込めない場合。
    """
    return validate_metric_sets(metric_set for source in sources for metric_set in _load_source(source))


def theme_primary_metric_keys(sources: Iterable[str] = THEME_METRIC_SOURCES) -> tuple[str, ...]:
    """テーマが CP のテナント一覧に出す主要指標のキーを返す（01 §13 #5）。

    Args:
        sources: 提供元（省略時は :data:`THEME_METRIC_SOURCES`）。

    Returns:
        tuple[str, ...]: 主要指標のキー（登録順）。
    """
    return tuple(key for metric_set in load_theme_metric_sets(sources) for key in metric_set.primary_keys)
