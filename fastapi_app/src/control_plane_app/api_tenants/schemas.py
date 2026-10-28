#!/usr/bin/env python
# coding:utf-8
"""テナント管理 API（``/api/v1/cp/tenants``）のリクエスト・レスポンスのスキーマ。

DB のテーブルモデル（``TTenant``）はそのまま返さず、公開してよい列だけをここで定義する。
``realm_name``（認証領域名）・``tier``・``created_by`` / ``updated_by`` は返さない（01 §10.2: 認証領域名はフロントに返さない）。
日時は UTC（``Z``）の ISO 8601（03 §4）。
"""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from control_plane_app.models.sql_models import ProvisioningType, RunStatus, TenantStatus
from control_plane_app.services.tenant_provisioning import TENANT_NAME_MAX_LENGTH
from modules.api_common.datetime_types import UtcDatetime
from modules.api_common.pagination import CursorPage


class TenantRead(BaseModel):
    """テナント（台帳の 1 行）。`ETag` ヘッダーと `version` は同じ値。"""

    id: uuid.UUID = Field(description="テナント ID（UUIDv7）")
    tenant_code: str = Field(description="テナントコード（URL に使う識別子。変更不可・再利用しない）")
    name: str = Field(description="テナント名")
    status: TenantStatus = Field(description="ライフサイクル状態")
    version: int = Field(description="楽観ロック用のバージョン。更新系の `If-Match` に `\"<version>\"` で指定する")
    created_at: UtcDatetime = Field(description="作成日時（UTC）")
    updated_at: UtcDatetime = Field(description="更新日時（UTC）")
    deletion_requested_at: UtcDatetime | None = Field(description="削除要求日時（UTC）。猶予期間（30 日）の起点")
    deleted_at: UtcDatetime | None = Field(description="削除日時（UTC）。物理削除の完了時刻")


class PrimaryMetricRead(BaseModel):
    """テナント一覧に出す、テーマ固有の主要指標(01 §13 #5)。直近の日次スナップショットの値。"""

    metric_key: str = Field(description="指標のキー(例: ToDo アプリでは `todo_count`)。表示名はフロントがキーから決める")
    value: Decimal | None = Field(description="指標の値(10 進数の文字列)。集計データが無ければ `null`")
    date: dt.date | None = Field(description="値の集計対象日(UTC)。集計データが無ければ `null`")


class TenantListItem(TenantRead):
    """テナント一覧の要素。直近の日次メトリクスのユーザー数と、テーマ固有の主要指標を含む。"""

    users_total: int | None = Field(default=None, description="ユーザー数（総数）。直近の日次スナップショット。データが無ければ `null`")
    users_active: int | None = Field(default=None, description="ユーザー数（有効数）。直近の日次スナップショット。データが無ければ `null`")
    metrics_date: dt.date | None = Field(default=None, description="ユーザー数の集計対象日（UTC）。データが無ければ `null`")
    primary_metrics: list[PrimaryMetricRead] = Field(description="テーマ固有の主要指標(テーマが宣言した順。テーマが宣言していなければ空配列)。集計前の指標は `value` が `null`")


class TenantPage(CursorPage[TenantListItem]):
    """テナント一覧（カーソル方式）。"""


class ProvisioningHistoryRead(BaseModel):
    """払い出し履歴の 1 件。`error` はステップ名・例外の型などの要約で、秘匿値を含まない。"""

    id: uuid.UUID = Field(description="履歴 ID")
    type: ProvisioningType = Field(description="種別（`onboard`: 払い出し、`offboard`: 削除）")
    status: RunStatus = Field(description="実行状態")
    step: str | None = Field(description="実行中・最後に実行したステップ名")
    error: str | None = Field(description="失敗時のエラーの要約")
    started_at: UtcDatetime = Field(description="開始日時（UTC）")
    finished_at: UtcDatetime | None = Field(description="終了日時（UTC）。実行中は `null`")


class TenantDetail(TenantRead):
    """テナント詳細。払い出し履歴（新しい順）を含む。"""

    provisioning_history: list[ProvisioningHistoryRead] = Field(description="払い出し履歴（新しい順）")


class InitialAdminInput(BaseModel):
    """初期管理者の入力。"""

    email: str = Field(min_length=3, max_length=254, description="メールアドレス（テナント内で一意）")
    username: str | None = Field(default=None, min_length=1, max_length=100, description="ユーザー名。省略時はメールアドレス")
    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="名。省略時は既定値")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="姓。省略時は既定値")


class TenantCreate(BaseModel):
    """テナント作成（払い出し）のリクエスト。"""

    tenant_code: str = Field(min_length=1, max_length=64, description="テナントコード（英小文字・数字・ハイフンの 3〜32 文字。予約語は不可）")
    name: str = Field(min_length=1, max_length=TENANT_NAME_MAX_LENGTH, description="テナント名")
    initial_admin: InitialAdminInput = Field(description="初期管理者")


class ProvisioningRetryRequest(BaseModel):
    """払い出しの再実行のリクエスト。初期管理者の情報は台帳に保存していないため、再度指定する。"""

    initial_admin: InitialAdminInput = Field(description="初期管理者")


class InitialAdminCredentials(BaseModel):
    """払い出された初期管理者のログイン情報。**一度だけ返す**。"""

    username: str = Field(description="ユーザー名")
    temporary_password: str = Field(repr=False, description="一時パスワード。初回ログイン時に変更が必要。**このレスポンスでのみ返し、どこにも保存されない**")


class TenantProvisioned(BaseModel):
    """払い出し（作成・再実行）の結果。レスポンスは `Cache-Control: no-store`。"""

    tenant: TenantRead = Field(description="払い出し後のテナント（`ACTIVE`）")
    initial_admin: InitialAdminCredentials = Field(description="初期管理者のログイン情報")
    provisioning_history_id: uuid.UUID = Field(description="払い出し履歴の ID")
