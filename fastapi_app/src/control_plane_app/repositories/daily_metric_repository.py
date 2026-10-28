#!/usr/bin/env python
# coding:utf-8
"""CP DB（``cp_runtime``）の日次メトリクス（``t_tenant_daily_metric``）の書き込み（01 CP-MET-05、02 §4.6）。

読み取り（一覧・推移・サマリー）は :mod:`control_plane_app.repositories.tenant_query`。
本モジュールの関数はコミットしない。
"""
import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from control_plane_app.models.sql_models import TTenantDailyMetric


def upsert_daily_metrics(session: Session, tenant_id: uuid.UUID, date: dt.date, values: Mapping[str, Decimal]) -> int:
    """テナントのある日の指標を UPSERT する（``ON CONFLICT (tenant_id, date, metric_key) DO UPDATE``）。

    同じ日に再実行した場合は値を上書きする（行は増えない）。値が変わらない行は更新しない（``updated_at`` も保つ）。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。
        date: 集計対象日（UTC）。
        values: 指標キーごとの値。

    Returns:
        int: 追加・更新した行数（値が変わらなかった行は含まない）。
    """
    if not values:
        return 0
    table = TTenantDailyMetric.__table__
    statement = insert(table).values([{"tenant_id": tenant_id, "date": date, "metric_key": key, "value": value} for key, value in values.items()])
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.tenant_id, table.c.date, table.c.metric_key],
        set_={"value": statement.excluded.value, "updated_at": func.now()},
        where=table.c.value.is_distinct_from(statement.excluded.value),
    )
    result = session.connection().execute(statement)
    return int(result.rowcount or 0)
