#!/usr/bin/env python
# coding:utf-8
"""メトリクス API（``/api/v1/cp``）のレスポンスのスキーマ。

指標の値は ``numeric``（浮動小数点を使わない。03 §4）のため、JSON では 10 進数の文字列（例: `"12"`）で返す。
"""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from control_plane_app.models.sql_models import TenantStatus


class DailyMetricRead(BaseModel):
    """日次メトリクスの 1 点。"""

    date: dt.date = Field(description="集計対象日（UTC）")
    metric_key: str = Field(description="指標のキー（例: `users_total`, `users_active`。テーマ固有の指標も同じ形）")
    value: Decimal = Field(description="指標の値（10 進数の文字列）")


class TenantMetricsRead(BaseModel):
    """テナントの日次メトリクスの推移。"""

    tenant_id: uuid.UUID = Field(description="テナント ID")
    from_date: dt.date = Field(description="期間の開始日（含む）")
    to_date: dt.date = Field(description="期間の終了日（含む）")
    items: list[DailyMetricRead] = Field(description="日付・指標キーの昇順。集計データが無ければ空")


class MetricTotalRead(BaseModel):
    """指標ごとの全テナント合計。"""

    metric_key: str = Field(description="指標のキー")
    value: Decimal = Field(description="削除済みを除く全テナントの最新値の合計（10 進数の文字列）")


class MetricsSummaryRead(BaseModel):
    """全テナント合計のサマリー（ダッシュボード用）。"""

    tenants_by_status: dict[TenantStatus, int] = Field(description="状態ごとのテナント数（全状態を 0 埋めして返す）")
    metrics: list[MetricTotalRead] = Field(description="指標ごとの合計。集計データが無ければ空")
    as_of: dt.date | None = Field(description="合計に使った最新値の集計対象日（UTC）の最大値。データが無ければ `null`")
