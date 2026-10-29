#!/usr/bin/env python
# coding:utf-8
""" アプリケーションプレーンのテナントスコープ・テーブル用の部品

    アプリケーションプレーン DB のテナントに属するテーブルは、すべて `tenant_id` を持ち、
    RLS(`modules.tenancy.rls.enable_tenant_rls`)でテナント境界を強制する。

    提供するもの:
        - `TenantScopedMixin`: `tenant_id`(uuid, NOT NULL, index)のみを持つミックスイン。
          中間テーブルなど、独自の主キーを持つテーブルで使う。
        - `TenantScopedBase`: `AppPlaneBase` + `tenant_id` + `id`(uuid, UUIDv7)。通常のエンティティはこれを継承する。
        - `tenant_scoped_unique()` / `tenant_scoped_fk()`: 複合キー `(tenant_id, id)` の制約を作るヘルパー。

    ID の方針:
        - ID は PostgreSQL の `uuid` 型とし、既定値は UUIDv7(Python 3.14 の `uuid.uuid7()`)。
          時系列順に並ぶため、B-tree インデックスの局所性が良い。
        - DB 側の既定値にも PostgreSQL 18 の `uuidv7()` を設定し、SQL で直接 INSERT した場合も UUIDv7 となる。

    外部キーの方針(テナント跨ぎの関連付けを DB レベルで防ぐ):
        - 参照される側は `(tenant_id, id)` の UNIQUE 制約を持つ(`tenant_scoped_unique()`)。
        - 参照する側は `(tenant_id, <参照列>)` -> `(tenant_id, id)` の複合外部キーを張る(`tenant_scoped_fk()`)。
          単独の `id` への外部キーは張らない。`tenant_id` を共有するため、別テナントの行は参照できない。

    例:
        class TTodo(TenantScopedBase, table=True):
            __tablename__ = "t_todo"
            __table_args__ = (
                tenant_scoped_unique(),
                tenant_scoped_fk("created_by", "t_user"),
                {"comment": "ToDoテーブル"},
            )
            created_by: uuid.UUID = Field(description="作成者のユーザーID")

        # マイグレーション(alembic/app/versions/)
        def upgrade() -> None:
            op.create_table("t_todo", ...)
            enable_tenant_rls("t_todo")

        def downgrade() -> None:
            disable_tenant_rls("t_todo")
            op.drop_table("t_todo")
"""
import uuid

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from main_app.models.base import AppPlaneBase

# テナントIDのカラム名(RLS ポリシーが参照する)
TENANT_ID_COLUMN = "tenant_id"


class TenantScopedMixin(SQLModel):
    """ テナントIDを持つテーブル用のミックスイン(テーブルは持たない)

        `AppPlaneBase` と組み合わせて使う。
        例: `class TTodoAssignee(TenantScopedMixin, AppPlaneBase, table=True): ...`
    """
    tenant_id: uuid.UUID = Field(
        description="テナントID",
        nullable=False, index=True)


class TenantScopedBase(TenantScopedMixin, AppPlaneBase):
    """ テナントスコープのエンティティの基底クラス(テーブルは持たない)

        `tenant_id` と UUIDv7 の `id`(主キー)を持つ。
        他テーブルから参照される場合は `__table_args__` に `tenant_scoped_unique()` を含めること。
    """
    id: uuid.UUID = Field(
        description="ID(UUIDv7)",
        default_factory=uuid.uuid7, primary_key=True,
        sa_column_kwargs={"server_default": text("uuidv7()")})


def tenant_scoped_unique() -> UniqueConstraint:
    """
        複合外部キーの参照先となる `(tenant_id, id)` の UNIQUE 制約を返す
        return: UniqueConstraint(制約名は命名規約により `<table>_tenant_id_id_key`)
    """
    return UniqueConstraint(TENANT_ID_COLUMN, "id")


def tenant_scoped_fk(column: str, referent_table: str, *, ondelete: str | None = None) -> ForeignKeyConstraint:
    """
        `(tenant_id, column)` -> `referent_table(tenant_id, id)` の複合外部キーを返す
        column: 参照元のカラム名(例: "created_by")
        referent_table: 参照先のテーブル名(例: "t_user")。参照先は `tenant_scoped_unique()` を持つこと
        ondelete: ON DELETE の動作(例: "CASCADE")
        return: ForeignKeyConstraint
    """
    return ForeignKeyConstraint(
        [TENANT_ID_COLUMN, column],
        [f"{referent_table}.{TENANT_ID_COLUMN}", f"{referent_table}.id"],
        ondelete=ondelete,
    )
