#!/usr/bin/env python
# coding:utf-8
"""ToDo のテーマ固有メトリクス（docs/spec/ToDoApp.md §7 #5。01 §13 #5 の拡張点）。

| 指標キー | 算出方法 |
| --- | --- |
| ``todo_count`` | 論理削除（``deleted_at``）を除く ToDo の総数。テナント一覧の主要指標 |
| ``todo_open_count`` | そのうち ``status = 'open'`` |
| ``todo_in_progress_count`` | そのうち ``status = 'in_progress'`` |
| ``todo_done_count`` | そのうち ``status = 'done'`` |

:data:`TODO_METRICS` を ``modules/tenant_metrics/registry.py`` の ``THEME_METRIC_SOURCES`` に登録している。
集計は CP の日次スナップショット（``metrics_snapshot``）から ``app_cp_agent`` のセッションで呼ばれる
（GUC 設定済み。RLS によりそのテナントの行だけが見える）。本モジュールは ``control_plane_app`` を import しない。
"""
import uuid
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlmodel import col

from main_app.models import TodoStatus, TTodo
from modules.tenant_metrics.definition import MetricValue, TenantMetricSet

METRIC_TODO_COUNT = "todo_count"
METRIC_TODO_OPEN_COUNT = "todo_open_count"
METRIC_TODO_IN_PROGRESS_COUNT = "todo_in_progress_count"
METRIC_TODO_DONE_COUNT = "todo_done_count"

# 指標キー -> 対象のステータス（None は全ステータス）
_STATUS_BY_METRIC: dict[str, TodoStatus | None] = {
    METRIC_TODO_COUNT: None,
    METRIC_TODO_OPEN_COUNT: TodoStatus.OPEN,
    METRIC_TODO_IN_PROGRESS_COUNT: TodoStatus.IN_PROGRESS,
    METRIC_TODO_DONE_COUNT: TodoStatus.DONE,
}


def collect_todo_metrics(session: Session, tenant_id: uuid.UUID) -> Mapping[str, MetricValue]:
    """テナントの ToDo の件数をステータス別に 1 回のクエリで集計する。

    論理削除済みの ToDo は数えない（03 §5.1。インデックス ``ix_t_todo_tenant_id_status`` の部分条件と一致する）。

    Args:
        session: GUC を ``tenant_id`` に設定済みの ``app_db`` のセッション（読み取りのみ）。
        tenant_id: テナント ID。

    Returns:
        Mapping[str, MetricValue]: 指標キーごとの件数（該当なしは 0）。
    """
    columns = [
        (func.count() if status is None else func.count().filter(col(TTodo.status) == status.value)).label(key)
        for key, status in _STATUS_BY_METRIC.items()
    ]
    statement = select(*columns).select_from(TTodo).where(col(TTodo.tenant_id) == tenant_id, col(TTodo.deleted_at).is_(None))
    row = session.connection().execute(statement).one()
    return {key: int(row._mapping[key]) for key in _STATUS_BY_METRIC}


# ToDo の指標セット（THEME_METRIC_SOURCES に登録する）
TODO_METRICS = TenantMetricSet(
    name="todo",
    keys=tuple(_STATUS_BY_METRIC),
    collect=collect_todo_metrics,
    primary_keys=(METRIC_TODO_COUNT,),
)
