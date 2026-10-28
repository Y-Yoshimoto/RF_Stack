#!/usr/bin/env python
# coding:utf-8
"""CP DB（``cp_runtime``）の読み取り専用クエリ（テナント一覧・日次メトリクス）。

API の一覧・詳細・メトリクス表示（01 CP-OPS-01, 02, CP-MET-01..05）のための参照系。書き込み・コミットはしない。
テナント台帳の更新は :mod:`control_plane_app.services.tenant_provisioning` が行う。

一覧はキーセット方式（カーソル）で取得する。並び替えキーと ``id`` の組を行値として比較するため、
並び替えキーが重複しても順序が安定する（03 §3）。
"""
import datetime as dt
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, tuple_
from sqlmodel import Session, col, select

from control_plane_app.models.sql_models import TenantStatus, TTenant, TTenantDailyMetric

# 並び替えに使えるキーと列。許可するキーはここで定義する（03 §3）。
SORT_COLUMNS: dict[str, Any] = {
    "created_at": col(TTenant.created_at),
    "tenant_code": col(TTenant.tenant_code),
    "name": col(TTenant.name),
}
DEFAULT_SORT = "-created_at"

# 一覧で表示するユーザー数の指標キー（01 CP-MET-01。日次メトリクスの ``metric_key``）。
METRIC_USERS_TOTAL = "users_total"
METRIC_USERS_ACTIVE = "users_active"


@dataclass(frozen=True, slots=True)
class TenantSort:
    """テナント一覧の並び順。

    Attributes:
        key: 並び替えキー（:data:`SORT_COLUMNS` のキー）。
        descending: 降順か。``id`` も同じ向きで並べる。
    """

    key: str
    descending: bool

    @classmethod
    def parse(cls, raw: str) -> "TenantSort":
        """``sort`` クエリの値（``created_at`` / ``-created_at``）を読む。

        Args:
            raw: クエリの値。

        Returns:
            TenantSort: 並び順。

        Raises:
            ValueError: 許可していないキーの場合。
        """
        descending = raw.startswith("-")
        key = raw[1:] if descending else raw
        if key not in SORT_COLUMNS:
            raise ValueError(f"unsupported sort key: {key}")
        return cls(key=key, descending=descending)

    def __str__(self) -> str:
        """``sort`` クエリと同じ表記にする。"""
        return f"{'-' if self.descending else ''}{self.key}"


@dataclass(frozen=True, slots=True)
class MetricValue:
    """最新の日次メトリクスの値。

    Attributes:
        date: 集計対象日。
        value: 値。
    """

    date: dt.date
    value: Decimal


def list_tenants(session: Session, *, sort: TenantSort, statuses: Collection[str] | None, after: tuple[Any, uuid.UUID] | None, limit: int) -> list[TTenant]:
    """テナントを並び順どおりに取得する（キーセット方式）。

    Args:
        session: CP DB のセッション。
        sort: 並び順。
        statuses: 絞り込む状態。``None`` なら絞り込まない（削除済みを含む）。
        after: 前のページの最後の要素の ``(並び替えキーの値, id)``。この次から取得する。
        limit: 取得件数。

    Returns:
        list[TTenant]: テナント（最大 ``limit`` 件）。
    """
    sort_column = SORT_COLUMNS[sort.key]
    id_column = col(TTenant.id)
    statement = select(TTenant)
    if statuses is not None:
        statement = statement.where(col(TTenant.status).in_(list(statuses)))
    if after is not None:
        row = tuple_(sort_column, id_column)
        statement = statement.where(row < tuple_(*after) if sort.descending else row > tuple_(*after))
    if sort.descending:
        statement = statement.order_by(sort_column.desc(), id_column.desc())
    else:
        statement = statement.order_by(sort_column.asc(), id_column.asc())
    return list(session.exec(statement.limit(limit)).all())


def count_tenants(session: Session, statuses: Collection[str] | None) -> int:
    """絞り込み後のテナント数を返す。

    Args:
        session: CP DB のセッション。
        statuses: 絞り込む状態。``None`` なら全件。

    Returns:
        int: 件数。
    """
    statement = select(func.count()).select_from(TTenant)
    if statuses is not None:
        statement = statement.where(col(TTenant.status).in_(list(statuses)))
    return int(session.exec(statement).one())


def latest_metric_values(session: Session, tenant_ids: Collection[uuid.UUID], metric_keys: Collection[str]) -> dict[uuid.UUID, dict[str, MetricValue]]:
    """テナントごと・指標ごとの最新の日次メトリクスを返す。

    Args:
        session: CP DB のセッション。
        tenant_ids: 対象のテナント ID。
        metric_keys: 対象の指標キー。

    Returns:
        dict: ``{tenant_id: {metric_key: MetricValue}}``。データの無いテナント・指標は含まれない。
    """
    if not tenant_ids or not metric_keys:
        return {}
    statement = (
        select(col(TTenantDailyMetric.tenant_id), col(TTenantDailyMetric.metric_key), col(TTenantDailyMetric.date), col(TTenantDailyMetric.value))
        .where(col(TTenantDailyMetric.tenant_id).in_(list(tenant_ids)), col(TTenantDailyMetric.metric_key).in_(list(metric_keys)))
        .distinct(col(TTenantDailyMetric.tenant_id), col(TTenantDailyMetric.metric_key))
        .order_by(col(TTenantDailyMetric.tenant_id), col(TTenantDailyMetric.metric_key), col(TTenantDailyMetric.date).desc())
    )
    result: dict[uuid.UUID, dict[str, MetricValue]] = {}
    for tenant_id, metric_key, date, value in session.exec(statement).all():
        result.setdefault(tenant_id, {})[metric_key] = MetricValue(date=date, value=value)
    return result


def list_daily_metrics(session: Session, tenant_id: uuid.UUID, date_from: dt.date, date_to: dt.date) -> Sequence[TTenantDailyMetric]:
    """テナントの日次メトリクスを期間で取得する（推移の表示用。01 CP-MET-05）。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。
        date_from: 開始日（含む）。
        date_to: 終了日（含む）。

    Returns:
        Sequence[TTenantDailyMetric]: 日付・指標キーの昇順。
    """
    statement = (
        select(TTenantDailyMetric)
        .where(TTenantDailyMetric.tenant_id == tenant_id, col(TTenantDailyMetric.date) >= date_from, col(TTenantDailyMetric.date) <= date_to)
        .order_by(col(TTenantDailyMetric.date), col(TTenantDailyMetric.metric_key))
    )
    return session.exec(statement).all()


def count_tenants_by_status(session: Session) -> dict[str, int]:
    """状態ごとのテナント数を返す（状態は全種類を 0 埋めする）。

    Args:
        session: CP DB のセッション。

    Returns:
        dict[str, int]: ``{status: 件数}``。
    """
    counts = {status.value: 0 for status in TenantStatus}
    rows = session.exec(select(col(TTenant.status), func.count()).group_by(col(TTenant.status))).all()
    for status, count in rows:
        counts[status] = int(count)
    return counts


def summarize_latest_metrics(session: Session) -> tuple[dt.date | None, dict[str, Decimal]]:
    """削除済み以外の全テナントについて、指標ごとに最新値を合計する（ダッシュボード用。01 CP-MET-04）。

    各テナント・各指標の最新の日次メトリクスを合計する。テナントによって最新日がずれていても合計に含める。

    Args:
        session: CP DB のセッション。

    Returns:
        tuple: ``(最新値の集計対象日の最大値, {metric_key: 合計})``。データが無ければ ``(None, {})``。
    """
    latest = (
        select(col(TTenantDailyMetric.tenant_id), col(TTenantDailyMetric.metric_key), col(TTenantDailyMetric.date), col(TTenantDailyMetric.value))
        .join(TTenant, col(TTenant.id) == col(TTenantDailyMetric.tenant_id))
        .where(col(TTenant.status) != TenantStatus.DELETED.value)
        .distinct(col(TTenantDailyMetric.tenant_id), col(TTenantDailyMetric.metric_key))
        .order_by(col(TTenantDailyMetric.tenant_id), col(TTenantDailyMetric.metric_key), col(TTenantDailyMetric.date).desc())
        .subquery("latest")
    )
    statement = select(latest.c.metric_key, func.sum(latest.c.value), func.max(latest.c.date)).group_by(latest.c.metric_key).order_by(latest.c.metric_key)
    totals: dict[str, Decimal] = {}
    as_of: dt.date | None = None
    for metric_key, total, max_date in session.exec(statement).all():
        totals[metric_key] = total
        as_of = max_date if as_of is None else max(as_of, max_date)
    return as_of, totals
