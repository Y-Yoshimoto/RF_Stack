#!/usr/bin/env python
# coding:utf-8
""" コントロールプレーン DB のテーブルモデル

    仕様の正は `docs/architecture/01-platform-concepts.md` §9.5(CP テーブル)と
    `docs/architecture/02-platform-implementation.md` §4。

    - t_tenant: テナント台帳
    - t_provisioning_history: 払い出し(オンボード/オフボード)の履歴
    - t_tenant_daily_metric: テナント毎の日次メトリクス(縦持ち)
    - t_scheduled_job_run: 定期ジョブの実行履歴
    - t_cp_audit_log: CP 監査ログ(追記のみ)

    テナントレジストリ公開ビュー `v_tenant_registry` はモデルを持たない(Alembic のリビジョン 0002 で作成する)。
    **新しいモデルを別モジュールに追加した場合は `alembic/control_plane/env.py` で import すること。**
"""
import datetime as dt
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Date, DateTime, Field, text

# コントロールプレーン用のベース(MetaData をプレーン毎に分離する)
from control_plane_app.models.base import ControlPlaneBase


class TenantStatus(StrEnum):
    """ テナントのライフサイクル状態(01 §6.1)

        `t_tenant.status` の CHECK 制約の正。
        `modules.tenancy.registry.TenantStatus`(AP 側でレジストリを読む際の定義)と値を一致させること。
    """
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"
    PENDING_DELETION = "PENDING_DELETION"
    DEPROVISIONING = "DEPROVISIONING"
    DELETED = "DELETED"


class ProvisioningType(StrEnum):
    """ 払い出しの種別 """
    ONBOARD = "onboard"
    OFFBOARD = "offboard"


class RunStatus(StrEnum):
    """ 払い出し・定期ジョブの実行状態 """
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    # 処理対象が無い・既に完了済み・ロックを取得できなかった等で何もしなかった
    SKIPPED = "SKIPPED"


# テナントコードの形式(01 §5.1)。予約語の拒否はアプリケーション層で行う
TENANT_CODE_PATTERN = r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}$"


def _in_values(column: str, values: type[StrEnum]) -> str:
    """ `column IN ('A', 'B', ...)` の CHECK 制約の式を返す(値は定数のみ) """
    return f"{column} IN ({', '.join(f"'{v.value}'" for v in values)})"


def _timestamptz_column(*, nullable: bool, server_default: bool = False, onupdate: bool = False) -> Column:
    """ タイムゾーン付き日時のカラムを返す(sa_column は使い回せないため毎回生成する) """
    return Column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=text("CURRENT_TIMESTAMP") if server_default else None,
        onupdate=func.now() if onupdate else None,
    )


def _uuid7_id_field() -> Any:
    """ UUIDv7 の主キー(DB 側の既定値も PostgreSQL 18 の uuidv7()) """
    return Field(
        description="ID(UUIDv7)",
        default_factory=uuid.uuid7, primary_key=True,
        sa_column_kwargs={"server_default": text("uuidv7()")})


# テナント台帳
class TTenant(ControlPlaneBase, table=True):
    """ テナント台帳

        - `tenant_code` / `realm_name` は DELETED 後も行を残して一意制約を維持する(再利用しない。01 CP-OPS-09)。
        - 楽観ロック(03 §5.2)の対象。更新時に `version` を +1 する。
    """
    __tablename__ = "t_tenant"
    __table_args__ = (
        CheckConstraint(_in_values("status", TenantStatus), name="status"),
        CheckConstraint(f"tenant_code ~ '{TENANT_CODE_PATTERN}'", name="tenant_code_format"),
        CheckConstraint("version >= 1", name="version_positive"),
        {"comment": "テナント台帳"},
    )
    id: uuid.UUID = _uuid7_id_field()
    tenant_code: str = Field(
        description="テナントコード(URL と認証領域名に使う。一意・変更不可・再利用しない)",
        sa_type=Text, unique=True, nullable=False)
    name: str = Field(
        description="テナント名",
        sa_type=Text, nullable=False)
    status: str = Field(
        description="ライフサイクル状態(TenantStatus)",
        default=TenantStatus.PROVISIONING.value,
        sa_type=Text, nullable=False,
        sa_column_kwargs={"server_default": TenantStatus.PROVISIONING.value})
    realm_name: str = Field(
        description="Keycloak のレルム名(tenant-{tenant_code})",
        sa_type=Text, unique=True, nullable=False)
    tier: str | None = Field(
        description="ティア(ティアリング導入時のための列。現フェーズでは使用しない)",
        default=None, sa_type=Text, nullable=True)
    version: int = Field(
        description="楽観ロック用のバージョン(作成時 1、更新毎に +1)",
        default=1, nullable=False,
        sa_column_kwargs={"server_default": text("1")})
    created_by: str | None = Field(
        description="作成者(CP 管理者の IdP subject。システムの場合は 'system')",
        default=None, sa_type=Text, nullable=True)
    updated_by: str | None = Field(
        description="最終更新者(CP 管理者の IdP subject。システムの場合は 'system')",
        default=None, sa_type=Text, nullable=True)
    created_at: dt.datetime = Field(
        description="作成日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
    updated_at: dt.datetime = Field(
        description="更新日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True, onupdate=True))
    deletion_requested_at: dt.datetime | None = Field(
        description="削除要求日時(PENDING_DELETION への遷移時刻。猶予期間の起点)",
        default=None, sa_column=_timestamptz_column(nullable=True))
    deleted_at: dt.datetime | None = Field(
        description="削除日時(DELETED への遷移時刻)",
        default=None, sa_column=_timestamptz_column(nullable=True))


# 払い出し履歴
class TProvisioningHistory(ControlPlaneBase, table=True):
    """ 払い出し履歴

        払い出し(onboard)・削除(offboard)の実行とステップの結果を記録する(01 CP-ONB-03, CP-ONB-08)。
        `error` に一時パスワード・シークレット等を含めないこと(01 CP-ONB-10)。
    """
    __tablename__ = "t_provisioning_history"
    __table_args__ = (
        CheckConstraint(_in_values("type", ProvisioningType), name="type"),
        CheckConstraint(_in_values("status", RunStatus), name="status"),
        Index("ix_t_provisioning_history_tenant_id_started_at", "tenant_id", "started_at"),
        {"comment": "払い出し履歴"},
    )
    id: uuid.UUID = _uuid7_id_field()
    tenant_id: uuid.UUID = Field(
        description="テナントID",
        foreign_key="t_tenant.id", nullable=False)
    type: str = Field(
        description="種別(onboard / offboard)",
        sa_type=Text, nullable=False)
    status: str = Field(
        description="実行状態(RunStatus)",
        default=RunStatus.RUNNING.value,
        sa_type=Text, nullable=False,
        sa_column_kwargs={"server_default": RunStatus.RUNNING.value})
    step: str | None = Field(
        description="ステップ名(実行中・最後に実行したステップ)",
        default=None, sa_type=Text, nullable=True)
    error: str | None = Field(
        description="エラー内容(秘匿値を含めない)",
        default=None, sa_type=Text, nullable=True)
    started_at: dt.datetime = Field(
        description="開始日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
    finished_at: dt.datetime | None = Field(
        description="終了日時(実行中は NULL)",
        default=None, sa_column=_timestamptz_column(nullable=True))
    created_at: dt.datetime = Field(
        description="作成日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
    updated_at: dt.datetime = Field(
        description="更新日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True, onupdate=True))


# 日次メトリクス(縦持ち)
class TTenantDailyMetric(ControlPlaneBase, table=True):
    """ テナント毎の日次メトリクス

        縦持ち(`metric_key`, `value`)とし、テーマ固有指標も同じ形で格納する(01 §9.5)。
        主キーは (tenant_id, date, metric_key)。日次スナップショットの再実行は UPSERT で上書きする。
    """
    __tablename__ = "t_tenant_daily_metric"
    __table_args__ = (
        Index("ix_t_tenant_daily_metric_date_metric_key", "date", "metric_key"),
        {"comment": "テナント日次メトリクス(縦持ち)"},
    )
    tenant_id: uuid.UUID = Field(
        description="テナントID",
        foreign_key="t_tenant.id", primary_key=True)
    date: dt.date = Field(
        description="集計対象日",
        sa_type=Date, primary_key=True)
    metric_key: str = Field(
        description="指標のキー(例: users_total, users_active。テーマ固有指標も同じ形)",
        sa_type=Text, primary_key=True)
    value: Decimal = Field(
        description="指標の値(浮動小数点は使わない)",
        sa_type=Numeric, nullable=False)
    created_at: dt.datetime = Field(
        description="作成日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
    updated_at: dt.datetime = Field(
        description="更新日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True, onupdate=True))


# 定期ジョブ実行履歴
class TScheduledJobRun(ControlPlaneBase, table=True):
    """ 定期ジョブの実行履歴(01 §12.1) """
    __tablename__ = "t_scheduled_job_run"
    __table_args__ = (
        CheckConstraint(_in_values("status", RunStatus), name="status"),
        Index("ix_t_scheduled_job_run_job_name_started_at", "job_name", "started_at"),
        {"comment": "定期ジョブ実行履歴"},
    )
    id: uuid.UUID = _uuid7_id_field()
    job_name: str = Field(
        description="ジョブ名(例: metrics_snapshot, tenant_purge, provisioning_reaper)",
        sa_type=Text, nullable=False)
    status: str = Field(
        description="実行状態(RunStatus)",
        default=RunStatus.RUNNING.value,
        sa_type=Text, nullable=False,
        sa_column_kwargs={"server_default": RunStatus.RUNNING.value})
    started_at: dt.datetime = Field(
        description="開始日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
    finished_at: dt.datetime | None = Field(
        description="終了日時(実行中は NULL)",
        default=None, sa_column=_timestamptz_column(nullable=True))
    error: str | None = Field(
        description="エラー内容(秘匿値を含めない)",
        default=None, sa_type=Text, nullable=True)
    created_at: dt.datetime = Field(
        description="作成日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
    updated_at: dt.datetime = Field(
        description="更新日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True, onupdate=True))


# CP 監査ログ
class TCpAuditLog(ControlPlaneBase, table=True):
    """ CP 監査ログ(03 §7)

        追記のみ(更新・削除しない)。リビジョン 0002 で実行時ロールの UPDATE / DELETE を剥奪している。
        業務データの変更と同じトランザクションで書く。`payload` に秘匿値を含めないこと。
        テナントが存在しない段階の操作(作成失敗等)も記録できるよう、`target_tenant_id` に外部キーは張らない。
    """
    __tablename__ = "t_cp_audit_log"
    __table_args__ = (
        Index("ix_t_cp_audit_log_target_tenant_id_created_at", "target_tenant_id", "created_at"),
        {"comment": "CP 監査ログ(追記のみ)"},
    )
    id: uuid.UUID = _uuid7_id_field()
    actor: str = Field(
        description="操作者(CP 管理者の IdP subject。システムの場合は 'system')",
        sa_type=Text, nullable=False)
    action: str = Field(
        description="操作(resource.verb 形式。例: tenant.suspend)",
        sa_type=Text, nullable=False)
    target_tenant_id: uuid.UUID | None = Field(
        description="対象テナントID",
        default=None, nullable=True)
    target_type: str | None = Field(
        description="対象の種別(例: tenant)",
        default=None, sa_type=Text, nullable=True)
    target_id: str | None = Field(
        description="対象のID",
        default=None, sa_type=Text, nullable=True)
    payload: dict | None = Field(
        description="変更前後の差分など(秘匿値を含めない)",
        default=None, sa_column=Column(JSONB, nullable=True))
    request_id: str | None = Field(
        description="リクエストID",
        default=None, sa_type=Text, nullable=True)
    created_at: dt.datetime = Field(
        description="記録日時",
        sa_column=_timestamptz_column(nullable=False, server_default=True))
