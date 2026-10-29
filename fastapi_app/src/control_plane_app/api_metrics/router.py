#!/usr/bin/env python
# coding:utf-8
"""メトリクス API（``/api/v1/cp``。01 §6.4、§10.2）。

日次ジョブが ``t_tenant_daily_metric`` に保存したスナップショットを読むだけで、AP DB には触れない。
認証・認可（``saas_admin`` / ``saas_viewer``）は ``control_plane_app.apiapp`` のルーターで適用済み。
"""
import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from control_plane_app.api_metrics.schemas import DailyMetricRead, MetricsSummaryRead, MetricTotalRead, TenantMetricsRead
from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.repositories import tenant_query
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.services.errors import TenantNotFoundError
from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text
from modules.errors.openapi import problem_responses
from modules.errors.problem import FieldError
from modules.tenancy.providers import CpSessionDep

router = APIRouter()

# 取得できる期間の最大日数と、期間を省略したときの日数。
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


@router.get(
    "/tenants/{tenant_id}/metrics",
    summary="テナントのメトリクス推移",
    responses=problem_responses(404, 422),
)
def get_tenant_metrics(
    tenant_id: uuid.UUID,
    session: CpSessionDep,
    from_date: Annotated[dt.date | None, Query(alias="from", description="開始日（含む。`YYYY-MM-DD`）。省略時は終了日の 29 日前")] = None,
    to_date: Annotated[dt.date | None, Query(alias="to", description="終了日（含む。`YYYY-MM-DD`）。省略時は今日（UTC）")] = None,
) -> TenantMetricsRead:
    """テナントの日次メトリクスの推移を返す（`saas_admin` / `saas_viewer`）。

    期間は最大 366 日。日次ジョブによる集計がまだ無い場合は `items` が空になる。
    """
    end = to_date or dt.datetime.now(dt.UTC).date()
    start = from_date or end - dt.timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise problem_from_text(422, "validation_error", text_for_code("validation_error", 422), errors=[FieldError(field="from", code="invalid_range", message="開始日は終了日以前にしてください")])
    if (end - start).days >= MAX_RANGE_DAYS:
        raise problem_from_text(422, "validation_error", text_for_code("validation_error", 422), errors=[FieldError(field="from", code="range_too_long", message=f"期間は最大 {MAX_RANGE_DAYS} 日です")])
    if repo.get_tenant(session, tenant_id) is None:
        raise TenantNotFoundError(tenant_id)
    rows = tenant_query.list_daily_metrics(session, tenant_id, start, end)
    return TenantMetricsRead(tenant_id=tenant_id, from_date=start, to_date=end, items=[DailyMetricRead.model_validate(row, from_attributes=True) for row in rows])


@router.get(
    "/metrics/summary",
    summary="全テナント合計のサマリー",
    responses=problem_responses(),
)
def get_metrics_summary(session: CpSessionDep) -> MetricsSummaryRead:
    """全テナント合計のサマリーを返す（`saas_admin` / `saas_viewer`）。

    状態ごとのテナント数と、指標ごとの最新値の合計（削除済みを除く）。集計データが無ければ `metrics` は空。
    """
    counts = tenant_query.count_tenants_by_status(session)
    as_of, totals = tenant_query.summarize_latest_metrics(session)
    return MetricsSummaryRead(
        tenants_by_status={TenantStatus(status): count for status, count in counts.items()},
        metrics=[MetricTotalRead(metric_key=key, value=value) for key, value in totals.items()],
        as_of=as_of,
    )
