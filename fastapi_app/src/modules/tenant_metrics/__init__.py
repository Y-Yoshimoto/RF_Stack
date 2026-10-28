"""テナント毎のメトリクス（日次スナップショット）の指標定義と、テーマ固有指標の拡張点（01 §6.4 CP-MET-02、§13 #5）。

プレーン非依存の部品。FastAPI・スケジューラに依存しない。

- :mod:`modules.tenant_metrics.definition` — 指標セット :class:`TenantMetricSet` と検証
- :mod:`modules.tenant_metrics.registry` — テーマ固有指標の登録箇所 :data:`THEME_METRIC_SOURCES`

集計の実行（``app_cp_agent`` でテナント毎に GUC を切り替える）は CP のリポジトリ
（``control_plane_app/repositories/app_tenant_metrics.py``）、CP DB への保存はジョブ
（``control_plane_app/jobs/metrics_snapshot.py``）が行う。
"""
from .definition import MetricValue, TenantMetricSet, validate_metric_sets
from .registry import THEME_METRIC_SOURCES, load_theme_metric_sets, theme_primary_metric_keys

__all__ = ["MetricValue", "TenantMetricSet", "validate_metric_sets", "THEME_METRIC_SOURCES", "load_theme_metric_sets", "theme_primary_metric_keys"]
