#!/usr/bin/env python
# coding:utf-8
"""CP から AP DB（``app_db``）のテナント毎のメトリクスを集計するリポジトリ（01 §4.3 #2、§6.4、02 §4.5）。

接続は ``app_cp_agent``（SELECT / DELETE のみ、RLS 適用）。テナントは
:func:`modules.tenancy.db.tenant_guc_scope` で GUC ``app.current_tenant`` を切り替えて集計するため、
RLS を迂回しない（01 §9.2）。将来 AP の利用イベント方式に移行する際は、本モジュールを差し替える。

集計する指標:
    - 基盤の指標（CP-MET-01）: :data:`USER_METRICS`（``users_total`` / ``users_active``。``t_user`` から）
    - テーマ固有の指標（CP-MET-02）: ``modules/tenant_metrics/registry.py`` の ``THEME_METRIC_SOURCES`` に登録された指標セット。
      ``control_plane_app`` は ``main_app`` を import しない（02 §5.1）ため、登録箇所から文字列で読み込む
"""
import uuid
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import Session

from control_plane_app.repositories.tenant_query import METRIC_USERS_ACTIVE, METRIC_USERS_TOTAL
from modules.tenancy.db import tenant_guc_scope
from modules.tenant_metrics.definition import MetricValue, TenantMetricSet, validate_metric_sets
from modules.tenant_metrics.registry import load_theme_metric_sets

# ユーザー数（総数・有効数）。ユーザーは論理削除せず is_active で無効化する（02 §4.7）。
_USER_COUNTS_SQL = text("SELECT count(*) AS total, count(*) FILTER (WHERE is_active) AS active FROM t_user WHERE tenant_id = :tenant_id")


def collect_user_metrics(session: OrmSession, tenant_id: uuid.UUID) -> Mapping[str, MetricValue]:
    """テナントのユーザー数（総数・有効数）を集計する（01 CP-MET-01）。

    Args:
        session: GUC を ``tenant_id`` に設定済みの ``app_db`` のセッション。
        tenant_id: テナント ID（RLS に加えた多重防御の条件）。

    Returns:
        Mapping[str, MetricValue]: ``users_total`` / ``users_active``。
    """
    row = session.connection().execute(_USER_COUNTS_SQL, {"tenant_id": tenant_id}).one()
    return {METRIC_USERS_TOTAL: int(row.total), METRIC_USERS_ACTIVE: int(row.active)}


# 基盤の指標セット（CP-MET-01）
USER_METRICS = TenantMetricSet(
    name="users",
    keys=(METRIC_USERS_TOTAL, METRIC_USERS_ACTIVE),
    collect=collect_user_metrics,
    primary_keys=(METRIC_USERS_TOTAL, METRIC_USERS_ACTIVE),
)


def default_metric_sets() -> tuple[TenantMetricSet, ...]:
    """基盤の指標セットと、登録されたテーマ固有の指標セットを返す（キーの重複を検証済み）。

    Returns:
        tuple[TenantMetricSet, ...]: 指標セット（基盤 → テーマの順）。

    Raises:
        ValueError: 指標キーが重複する、または登録が不正な場合。
        ImportError: テーマのモジュールを読み込めない場合。
    """
    return validate_metric_sets((USER_METRICS, *load_theme_metric_sets()))


def _default_engine_factory() -> Engine:
    """``app_cp_agent`` のエンジンを返す（providers は FastAPI を import するため遅延 import する）。"""
    from modules.tenancy.providers import get_app_cp_agent_engine

    return get_app_cp_agent_engine()


class AppTenantMetricsRepository:
    """AP DB のテナント毎のメトリクスの集計。

    Args:
        engine_factory: ``app_cp_agent`` のエンジンを返す関数（最初の集計まで呼ばない）。
            省略時は :func:`modules.tenancy.providers.get_app_cp_agent_engine`。
        metric_sets: 指標セット。省略時は :func:`default_metric_sets`（基盤 + テーマ）。
    """

    def __init__(self, engine_factory: Callable[[], Engine] | None = None, metric_sets: Sequence[TenantMetricSet] | None = None) -> None:
        """エンジンの取得方法と指標セットを保持する。"""
        self._engine_factory = engine_factory or _default_engine_factory
        self._metric_sets = validate_metric_sets(metric_sets) if metric_sets is not None else default_metric_sets()

    @property
    def metric_keys(self) -> list[str]:
        """集計する指標キーの一覧を返す（指標セットの順）。"""
        return [key for metric_set in self._metric_sets for key in metric_set.keys]

    def collect_tenant_metrics(self, tenant_id: uuid.UUID) -> dict[str, Decimal]:
        """テナントのすべての指標を 1 つの読み取りトランザクションで集計する。

        トランザクションは ``REPEATABLE READ``（指標セット間で同じ時点のデータを見る）とし、
        書き込まないため最後にロールバックする。

        Args:
            tenant_id: テナント ID。

        Returns:
            dict[str, Decimal]: 指標キーごとの値。

        Raises:
            ValueError: 集計関数の戻り値が約束に反する場合。
            sqlalchemy.exc.SQLAlchemyError: DB の操作に失敗した場合。
        """
        values: dict[str, Decimal] = {}
        engine = self._engine_factory().execution_options(isolation_level="REPEATABLE READ")
        with Session(engine) as session:
            try:
                with tenant_guc_scope(session, tenant_id):
                    for metric_set in self._metric_sets:
                        values.update(metric_set.collect_values(session, tenant_id))
            finally:
                session.rollback()
        return values
