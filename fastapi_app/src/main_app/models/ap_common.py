#!/usr/bin/env python
# coding:utf-8
""" アプリケーションプレーンの共通テーブル(ユーザー・組織・組織メンバー・AP 監査ログ)

    仕様の正は `docs/architecture/01-platform-concepts.md` §8・§9.4 と `03-conventions.md`。
    スキーマはリビジョン `alembic/app/versions/0001_create_ap_common_tables.py`。

    - t_user: テナント内のユーザー(IdP のユーザーと `idp_subject` で対応付ける)
    - t_organization: 組織(論理削除。初期はフラット構造)
    - t_organization_member: 組織の所属(ユーザーは複数の組織に所属できる)
    - t_ap_audit_log: AP 監査ログ(追記のみ。`app_runtime` から UPDATE / DELETE を剥奪している)

    すべてテナントスコープのテーブル(`tenant_id` NOT NULL、複合外部キー、RLS)。
    参照される側は `UNIQUE (tenant_id, id)` を持ち、外部キーは `(tenant_id, <列>) -> (tenant_id, id)` で張る。
    ON DELETE は指定しない(物理削除はテナント物理削除でのみ行い、子テーブルから順に削除する)。
"""
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, Column, Index, PrimaryKeyConstraint, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field

from main_app.models.base import AppPlaneBase
from main_app.models.columns import NOT_DELETED, created_at_field, deleted_at_field, timestamptz_column, updated_at_field, version_field, version_positive_check
from modules.tenancy.models import TenantScopedBase, TenantScopedMixin, tenant_scoped_fk, tenant_scoped_unique


# ユーザー
class TUser(TenantScopedBase, table=True):
    """ テナント内のユーザー(01 §8 PF-USR-01〜06)

        - `(tenant_id, idp_subject)` と `(tenant_id, lower(email))` でテナント内一意。
          別テナントの同一メールアドレスは別ユーザー(PF-USR-06)。
        - ユーザーは論理削除せず、`is_active` で無効化する(PF-USR-03)。
        - `email` は IdP 側で未設定の場合に備えて NULL を許可する(NULL 同士は一意制約に掛からない)。
        - 楽観ロック(03 §5.2)の対象(`PATCH /api/v1/users/{id}`)。
        - `first_name` / `last_name` / `roles` は Keycloak が正で、一覧表示用の写し(ログイン時の同期と管理者の変更時に更新する。01 §9.4)。
          `roles` は `tenant_admin` / `member` のみ(CHECK)。同期前の行は `{}`(空配列)。
    """
    __tablename__ = "t_user"
    __table_args__ = (
        tenant_scoped_unique(),
        UniqueConstraint("tenant_id", "idp_subject"),
        Index("t_user_tenant_id_lower_email_key", "tenant_id", text("lower(email)"), unique=True),
        tenant_scoped_fk("created_by", "t_user"),
        tenant_scoped_fk("updated_by", "t_user"),
        version_positive_check(),
        CheckConstraint("roles <@ ARRAY['tenant_admin', 'member']::text[]", name="roles"),
        {"comment": "ユーザー(テナント内)"},
    )
    idp_subject: str = Field(
        description="IdP の利用者ID(Keycloak のテナントレルムの sub)",
        sa_type=Text, nullable=False)
    email: str | None = Field(
        description="メールアドレス(テナント内で大文字小文字を区別せず一意)",
        default=None, sa_type=Text, nullable=True)
    display_name: str = Field(
        description="表示名(ログイン時に IdP から同期する)",
        sa_type=Text, nullable=False)
    first_name: str | None = Field(
        description="名(Keycloak が正で、一覧表示用の写し。未同期は NULL)",
        default=None, sa_type=Text, nullable=True)
    last_name: str | None = Field(
        description="姓(Keycloak が正で、一覧表示用の写し。未同期は NULL)",
        default=None, sa_type=Text, nullable=True)
    roles: list[str] = Field(
        description="ロール(Keycloak が正で、一覧表示用の写し。tenant_admin / member。未同期は空配列)",
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")))
    is_active: bool = Field(
        description="有効フラグ(false = 無効化。IdP 側も無効化する)",
        default=True, nullable=False,
        sa_column_kwargs={"server_default": text("true")})
    last_login_at: dt.datetime | None = Field(
        description="最終ログイン日時(ログイン完了時に更新。トークン更新では更新しない)",
        default=None, sa_column=timestamptz_column(nullable=True))
    version: int = version_field()
    created_by: uuid.UUID | None = Field(
        description="作成者のユーザーID(ログイン時の自動作成・払い出し等のシステム処理は NULL)",
        default=None, nullable=True)
    updated_by: uuid.UUID | None = Field(
        description="最終更新者のユーザーID(ログイン時の同期等のシステム処理は NULL)",
        default=None, nullable=True)
    created_at: dt.datetime = created_at_field()
    updated_at: dt.datetime = updated_at_field()


# 組織
class TOrganization(TenantScopedBase, table=True):
    """ 組織(01 §8 PF-ORG-01〜04)

        - 削除は論理削除(`deleted_at`)。名前は有効な組織の中でテナント内一意(大文字小文字を区別しない)。
        - 楽観ロック(03 §5.2)の対象(`PATCH` / `DELETE /api/v1/organizations/{id}`、メンバーの全置換)。
    """
    __tablename__ = "t_organization"
    __table_args__ = (
        tenant_scoped_unique(),
        Index("t_organization_tenant_id_lower_name_key", "tenant_id", text("lower(name)"), unique=True, postgresql_where=text(NOT_DELETED)),
        tenant_scoped_fk("created_by", "t_user"),
        tenant_scoped_fk("updated_by", "t_user"),
        version_positive_check(),
        {"comment": "組織(テナント内。論理削除)"},
    )
    name: str = Field(
        description="組織名(有効な組織の中でテナント内一意)",
        sa_type=Text, nullable=False)
    version: int = version_field()
    created_by: uuid.UUID | None = Field(
        description="作成者のユーザーID(払い出し時のデフォルト組織等のシステム処理は NULL)",
        default=None, nullable=True)
    updated_by: uuid.UUID | None = Field(
        description="最終更新者のユーザーID(システム処理は NULL)",
        default=None, nullable=True)
    created_at: dt.datetime = created_at_field()
    updated_at: dt.datetime = updated_at_field()
    deleted_at: dt.datetime | None = deleted_at_field()


# 組織メンバー
class TOrganizationMember(TenantScopedMixin, AppPlaneBase, table=True):
    """ 組織の所属(01 §8 PF-ORG-02)

        主キーは `(tenant_id, organization_id, user_id)`。メンバーの変更は行の追加・削除で行う(更新しない)。
        組織を論理削除しても所属の行は残す(閲覧範囲の判定では削除済みの組織を除外する)。
    """
    __tablename__ = "t_organization_member"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "organization_id", "user_id"),
        tenant_scoped_fk("organization_id", "t_organization"),
        tenant_scoped_fk("user_id", "t_user"),
        Index("ix_t_organization_member_tenant_id_user_id", "tenant_id", "user_id"),
        {"comment": "組織メンバー"},
    )
    organization_id: uuid.UUID = Field(
        description="組織ID",
        nullable=False)
    user_id: uuid.UUID = Field(
        description="ユーザーID",
        nullable=False)
    created_at: dt.datetime = created_at_field()
    updated_at: dt.datetime = updated_at_field()


# AP 監査ログ
class TApAuditLog(TenantScopedBase, table=True):
    """ AP 監査ログ(03 §7)

        - 追記のみ。リビジョン 0001 で `app_runtime` の UPDATE / DELETE を剥奪している。
          削除はテナント物理削除(`app_cp_agent`)でのみ行う。
        - 業務データの変更と同じトランザクションで書く。`payload` に秘匿値を含めないこと。
        - 操作者・対象は削除や別種別の行を指しうるため、外部キーは張らない。`updated_at` は持たない。
    """
    __tablename__ = "t_ap_audit_log"
    __table_args__ = (
        Index("ix_t_ap_audit_log_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_t_ap_audit_log_tenant_id_target_type_target_id", "tenant_id", "target_type", "target_id"),
        {"comment": "AP 監査ログ(追記のみ)"},
    )
    actor_id: uuid.UUID | None = Field(
        description="操作者のユーザーID(システム処理は NULL)",
        default=None, nullable=True)
    action: str = Field(
        description="操作(resource.verb 形式。例: organization.create, todo.update)",
        sa_type=Text, nullable=False)
    target_type: str | None = Field(
        description="対象の種別(例: user, organization, todo)",
        default=None, sa_type=Text, nullable=True)
    target_id: str | None = Field(
        description="対象のID",
        default=None, sa_type=Text, nullable=True)
    payload: dict[str, Any] | None = Field(
        description="変更前後の差分など(秘匿値を含めない)",
        default=None, sa_column=Column(JSONB, nullable=True))
    request_id: str | None = Field(
        description="リクエストID",
        default=None, sa_type=Text, nullable=True)
    created_at: dt.datetime = created_at_field("記録日時")
