#!/usr/bin/env python
# coding:utf-8
""" ToDo のテーブル(ToDo・公開先組織・担当者・アクティビティ)

    仕様の正は `docs/spec/ToDoApp.md` §4(AP-TODO / AP-VIS / AP-ASN / AP-ACT)・§5・§9.1。
    スキーマはリビジョン `alembic/app/versions/0002_create_todo_tables.py`。

    - t_todo: ToDo(論理削除・楽観ロック)
    - t_todo_organization: 閲覧範囲が `organization` のときの公開先組織
    - t_todo_assignee: 担当者
    - t_todo_activity: アクティビティ(利用者に見せる変更履歴。AP 監査ログとは別)

    列挙値は PostgreSQL の enum 型ではなく text + CHECK 制約とする(ToDoApp.md §9.1)。
    値の正は本モジュールの StrEnum。値を変える場合は CHECK 制約を変えるリビジョンも作ること。

    DB では強制せず、アプリ層で検証するもの:
        - 担当者は最大 20 人(AP-ASN-01)。無効化されたユーザーを新たに割り当てない(AP-ASN-02)
        - `visibility = 'organization'` のとき公開先組織が 1 つ以上あること(AP-VIS-07)
        - 削除済みの組織を新たに公開先に指定しない
"""
import datetime as dt
import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Column, Date, Index, PrimaryKeyConstraint, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from main_app.models.base import AppPlaneBase
from main_app.models.columns import NOT_DELETED, created_at_field, deleted_at_field, in_values_check, updated_at_field, version_field, version_positive_check
from modules.tenancy.models import TenantScopedBase, TenantScopedMixin, tenant_scoped_fk, tenant_scoped_unique

# タイトル・説明の長さ(AP-TODO-04)
TODO_TITLE_MAX_LENGTH = 200
TODO_DESCRIPTION_MAX_LENGTH = 10_000
# 担当者の上限(AP-ASN-01。DB では強制しない)
TODO_ASSIGNEES_MAX = 20


class TodoStatus(StrEnum):
    """ ToDo のステータス(AP-TODO-02) """
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TodoPriority(StrEnum):
    """ ToDo の優先度(AP-TODO-03) """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TodoVisibility(StrEnum):
    """ ToDo の閲覧範囲(AP-VIS-01) """
    PRIVATE = "private"
    ORGANIZATION = "organization"
    TENANT = "tenant"


class TodoActivityAction(StrEnum):
    """ アクティビティの種別(AP-ACT-01)

        1 回の更新で複数の種別に当たる変更をした場合は、種別毎に 1 行ずつ記録する想定。
    """
    CREATED = "created"
    UPDATED = "updated"  # 項目(タイトル・説明・期限・優先度)の変更
    STATUS_CHANGED = "status_changed"
    ASSIGNEES_CHANGED = "assignees_changed"
    VISIBILITY_CHANGED = "visibility_changed"  # 閲覧範囲・公開先組織の変更
    DELETED = "deleted"


# ToDo
class TTodo(TenantScopedBase, table=True):
    """ ToDo(AP-TODO-01〜08)

        - 削除は論理削除(`deleted_at`)。既定のクエリは `deleted_at IS NULL` で除外する(03 §5.1)。
          一覧用のインデックスは `deleted_at IS NULL` の部分インデックス(クエリにこの条件が無いと使われない)。
        - 楽観ロック(03 §5.2)の対象。更新時に `version` を +1 し、`updated_by` を設定する。
    """
    __tablename__ = "t_todo"
    __table_args__ = (
        tenant_scoped_unique(),
        tenant_scoped_fk("created_by", "t_user"),
        tenant_scoped_fk("updated_by", "t_user"),
        in_values_check("status", TodoStatus),
        in_values_check("priority", TodoPriority),
        in_values_check("visibility", TodoVisibility),
        CheckConstraint(f"char_length(title) BETWEEN 1 AND {TODO_TITLE_MAX_LENGTH}", name="title_length"),
        CheckConstraint(f"description IS NULL OR char_length(description) <= {TODO_DESCRIPTION_MAX_LENGTH}", name="description_length"),
        version_positive_check(),
        Index("ix_t_todo_tenant_id_status", "tenant_id", "status", postgresql_where=text(NOT_DELETED)),
        Index("ix_t_todo_tenant_id_due_date", "tenant_id", "due_date", postgresql_where=text(NOT_DELETED)),
        Index("ix_t_todo_tenant_id_created_by", "tenant_id", "created_by", postgresql_where=text(NOT_DELETED)),
        {"comment": "ToDo(論理削除・楽観ロック)"},
    )
    created_by: uuid.UUID = Field(
        description="作成者のユーザーID",
        nullable=False)
    updated_by: uuid.UUID = Field(
        description="最終更新者のユーザーID(作成時は作成者)",
        nullable=False)
    title: str = Field(
        description=f"タイトル(必須。1〜{TODO_TITLE_MAX_LENGTH} 文字)",
        sa_type=Text, nullable=False)
    description: str | None = Field(
        description=f"説明(任意。最大 {TODO_DESCRIPTION_MAX_LENGTH:,} 文字)",
        default=None, sa_type=Text, nullable=True)
    status: str = Field(
        description="ステータス(TodoStatus: open / in_progress / done)",
        default=TodoStatus.OPEN.value,
        sa_type=Text, nullable=False,
        sa_column_kwargs={"server_default": TodoStatus.OPEN.value})
    priority: str = Field(
        description="優先度(TodoPriority: low / medium / high)",
        default=TodoPriority.MEDIUM.value,
        sa_type=Text, nullable=False,
        sa_column_kwargs={"server_default": TodoPriority.MEDIUM.value})
    due_date: dt.date | None = Field(
        description="期限(任意。時刻を持たない日付)",
        default=None, sa_type=Date, nullable=True)
    visibility: str = Field(
        description="閲覧範囲(TodoVisibility: private / organization / tenant)",
        default=TodoVisibility.PRIVATE.value,
        sa_type=Text, nullable=False,
        sa_column_kwargs={"server_default": TodoVisibility.PRIVATE.value})
    version: int = version_field()
    created_at: dt.datetime = created_at_field()
    updated_at: dt.datetime = updated_at_field()
    deleted_at: dt.datetime | None = deleted_at_field()


# ToDo の公開先組織
class TTodoOrganization(TenantScopedMixin, AppPlaneBase, table=True):
    """ ToDo の公開先組織(AP-VIS-03, 07, 08)

        `visibility = 'organization'` のときの対象組織。主キーは `(tenant_id, todo_id, organization_id)`。
        組織が論理削除されても行は残し、閲覧範囲の判定で除外する(AP-VIS-08)。
    """
    __tablename__ = "t_todo_organization"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "todo_id", "organization_id"),
        tenant_scoped_fk("todo_id", "t_todo"),
        tenant_scoped_fk("organization_id", "t_organization"),
        Index("ix_t_todo_organization_tenant_id_organization_id", "tenant_id", "organization_id"),
        {"comment": "ToDo の公開先組織"},
    )
    todo_id: uuid.UUID = Field(
        description="ToDo ID",
        nullable=False)
    organization_id: uuid.UUID = Field(
        description="公開先の組織ID",
        nullable=False)
    created_at: dt.datetime = created_at_field()
    updated_at: dt.datetime = updated_at_field()


# ToDo の担当者
class TTodoAssignee(TenantScopedMixin, AppPlaneBase, table=True):
    """ ToDo の担当者(AP-ASN-01〜05)

        主キーは `(tenant_id, todo_id, user_id)`。担当者の全置換(AP-ASN-05)では、残る担当者の行は維持し
        (`assigned_at` / `assigned_by` を保つ)、外れた担当者を削除・新しい担当者を追加する想定。
        担当者が無効化されても行は残す(AP-ASN-04)。
    """
    __tablename__ = "t_todo_assignee"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "todo_id", "user_id"),
        tenant_scoped_fk("todo_id", "t_todo"),
        tenant_scoped_fk("user_id", "t_user"),
        tenant_scoped_fk("assigned_by", "t_user"),
        Index("ix_t_todo_assignee_tenant_id_user_id", "tenant_id", "user_id"),
        {"comment": "ToDo の担当者"},
    )
    todo_id: uuid.UUID = Field(
        description="ToDo ID",
        nullable=False)
    user_id: uuid.UUID = Field(
        description="担当者のユーザーID",
        nullable=False)
    assigned_at: dt.datetime = created_at_field("割り当て日時")
    assigned_by: uuid.UUID = Field(
        description="割り当てたユーザーID",
        nullable=False)
    created_at: dt.datetime = created_at_field()
    updated_at: dt.datetime = updated_at_field()


# ToDo アクティビティ
class TTodoActivity(TenantScopedBase, table=True):
    """ ToDo アクティビティ(AP-ACT-01〜04)

        利用者に見せる変更履歴。ToDo の変更と同じトランザクションで記録する(AP-ACT-03)。
        追記のみで更新しないため `updated_at` は持たない。ToDo を論理削除しても行は残す。
    """
    __tablename__ = "t_todo_activity"
    __table_args__ = (
        tenant_scoped_fk("todo_id", "t_todo"),
        tenant_scoped_fk("actor_id", "t_user"),
        in_values_check("action", TodoActivityAction),
        Index("ix_t_todo_activity_tenant_id_todo_id_created_at", "tenant_id", "todo_id", "created_at"),
        {"comment": "ToDo アクティビティ(変更履歴)"},
    )
    todo_id: uuid.UUID = Field(
        description="ToDo ID",
        nullable=False)
    actor_id: uuid.UUID = Field(
        description="操作者のユーザーID",
        nullable=False)
    action: str = Field(
        description="種別(TodoActivityAction)",
        sa_type=Text, nullable=False)
    payload: dict[str, Any] = Field(
        description="変更前後の差分(例: {\"status\": {\"before\": \"open\", \"after\": \"done\"}})",
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")))
    created_at: dt.datetime = created_at_field("記録日時")
