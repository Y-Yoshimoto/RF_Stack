#!/usr/bin/env python
# coding:utf-8
"""テナント一覧のカーソル・並び替え・絞り込みの解釈（03 §3）。"""
import datetime as dt
import uuid
from typing import Any

from sqlmodel import Session

from control_plane_app.api_tenants.schemas import TenantListItem, TenantPage
from control_plane_app.models.sql_models import TenantStatus, TTenant
from control_plane_app.repositories import tenant_query
from modules.api_common.pagination import decode_cursor, encode_cursor, invalid_cursor_error
from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text
from modules.errors.problem import FieldError, ProblemError


def _query_error(field: str, code: str, message: str) -> ProblemError:
    """クエリパラメータの検証エラー（422）を作る。"""
    return problem_from_text(422, "validation_error", text_for_code("validation_error", 422), errors=[FieldError(field=field, code=code, message=message)])


def parse_sort(raw: str) -> tenant_query.TenantSort:
    """`sort` クエリを読む。

    Raises:
        ProblemError(422): 許可していないキーの場合。
    """
    try:
        return tenant_query.TenantSort.parse(raw)
    except ValueError:
        allowed = ", ".join(tenant_query.SORT_COLUMNS)
        raise _query_error("sort", "invalid_sort", f"並び替えに使えるキーは {allowed} です（先頭に - を付けると降順）") from None


def parse_statuses(raw: str | None) -> list[str] | None:
    """`status` クエリ（カンマ区切り）を読む。

    Raises:
        ProblemError(422): 未知の状態が含まれる場合。
    """
    if raw is None or not raw.strip():
        return None
    values = [value.strip() for value in raw.split(",") if value.strip()]
    known = {status.value for status in TenantStatus}
    if not values or any(value not in known for value in values):
        raise _query_error("status", "invalid_status", f"状態は {', '.join(sorted(known))} から指定してください")
    return values


def _sort_value(tenant: TTenant, key: str) -> Any:
    """カーソルに入れる、並び替えキーの値（JSON にできる形）。"""
    value = getattr(tenant, key)
    return value.isoformat() if isinstance(value, dt.datetime) else value


def _decode_after(cursor: str, sort: tenant_query.TenantSort) -> tuple[Any, uuid.UUID]:
    """カーソルを読み、キーセットの値にする。

    Raises:
        ProblemError(422): 壊れている、または並び替えの指定が現在の `sort` と異なる場合。
    """
    payload = decode_cursor(cursor)
    try:
        if payload["s"] != str(sort):
            raise invalid_cursor_error()
        raw_value, raw_id = payload["k"], payload["i"]
        value = dt.datetime.fromisoformat(raw_value) if sort.key == "created_at" else str(raw_value)
        if isinstance(value, dt.datetime) and value.tzinfo is None:
            raise invalid_cursor_error()
        return value, uuid.UUID(str(raw_id))
    except (KeyError, TypeError, ValueError):
        raise invalid_cursor_error() from None


def build_tenant_page(session: Session, *, limit: int, cursor: str | None, include_total: bool, sort: str, status_filter: str | None) -> TenantPage:
    """テナント一覧の 1 ページを組み立てる。

    Args:
        session: CP DB のセッション。
        limit: 1 ページの件数。
        cursor: 前のページの `next_cursor`。
        include_total: 総件数を含めるか。
        sort: `sort` クエリ。
        status_filter: `status` クエリ。

    Returns:
        TenantPage: 一覧。
    """
    parsed_sort = parse_sort(sort)
    statuses = parse_statuses(status_filter)
    after = _decode_after(cursor, parsed_sort) if cursor else None

    rows = tenant_query.list_tenants(session, sort=parsed_sort, statuses=statuses, after=after, limit=limit + 1)
    page_rows, has_more = rows[:limit], len(rows) > limit
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"s": str(parsed_sort), "k": _sort_value(last, parsed_sort.key), "i": str(last.id)})

    metrics = tenant_query.latest_metric_values(session, [row.id for row in page_rows], [tenant_query.METRIC_USERS_TOTAL, tenant_query.METRIC_USERS_ACTIVE])
    items = [_to_item(row, metrics.get(row.id, {})) for row in page_rows]
    total = tenant_query.count_tenants(session, statuses) if include_total else None
    return TenantPage(items=items, next_cursor=next_cursor, total=total)


def _to_item(tenant: TTenant, metrics: dict[str, tenant_query.MetricValue]) -> TenantListItem:
    """テナントと直近のユーザー数から一覧の要素を作る。"""
    total = metrics.get(tenant_query.METRIC_USERS_TOTAL)
    active = metrics.get(tenant_query.METRIC_USERS_ACTIVE)
    dates = [metric.date for metric in (total, active) if metric is not None]
    return TenantListItem.model_validate(
        {
            **{name: getattr(tenant, name) for name in ("id", "tenant_code", "name", "status", "version", "created_at", "updated_at", "deletion_requested_at", "deleted_at")},
            "users_total": int(total.value) if total is not None else None,
            "users_active": int(active.value) if active is not None else None,
            "metrics_date": max(dates) if dates else None,
        }
    )
