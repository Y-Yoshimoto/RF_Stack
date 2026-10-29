"""create todo tables

ToDo のテーブル(ToDoApp.md §5・§9.1)を作成する。モデルは main_app.models.todo。

- t_todo / t_todo_organization / t_todo_assignee / t_todo_activity。すべてテナントスコープのテーブル
  (tenant_id NOT NULL、複合外部キー、RLS)。t_user / t_organization(0001)を参照する。
- 列挙値(status / priority / visibility / action)は enum 型ではなく text + CHECK 制約(ToDoApp.md §9.1)。
  値はモデルを import せずリテラルで持つ(後からモデルが変わっても本リビジョンの意味を変えないため)。
- t_todo の一覧用インデックスは deleted_at IS NULL の部分インデックス(論理削除済みは既定のクエリから除外する)。
- RLS(ENABLE / FORCE + ポリシー tenant_isolation)は autogenerate が検出しないため手で追記している。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 18:22:41.634394

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 # autogenerate が sqlmodel.sql.sqltypes.AutoString を出力するため
from sqlalchemy.dialects import postgresql

from alembic import op
from modules.tenancy.rls import disable_tenant_rls, enable_tenant_rls

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 本リビジョンで作成するテナントスコープのテーブル(作成順。RLS の設定対象)
TENANT_SCOPED_TABLES = ("t_todo", "t_todo_activity", "t_todo_assignee", "t_todo_organization")


def upgrade() -> None:
    """Upgrade schema."""
    # --- ToDo(論理削除・楽観ロック) ---
    op.create_table('t_todo',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='open', nullable=False),
    sa.Column('priority', sa.Text(), server_default='medium', nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('visibility', sa.Text(), server_default='private', nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("priority IN ('low', 'medium', 'high')", name=op.f('t_todo_priority_check')),
    sa.CheckConstraint("status IN ('open', 'in_progress', 'done')", name=op.f('t_todo_status_check')),
    sa.CheckConstraint("visibility IN ('private', 'organization', 'tenant')", name=op.f('t_todo_visibility_check')),
    sa.CheckConstraint('char_length(title) BETWEEN 1 AND 200', name=op.f('t_todo_title_length_check')),
    sa.CheckConstraint('description IS NULL OR char_length(description) <= 10000', name=op.f('t_todo_description_length_check')),
    sa.CheckConstraint('version >= 1', name=op.f('t_todo_version_positive_check')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_tenant_id_created_by_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'updated_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_tenant_id_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_todo_pkey')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('t_todo_tenant_id_id_key')),
    comment='ToDo(論理削除・楽観ロック)'
    )
    op.create_index(op.f('ix_t_todo_tenant_id'), 't_todo', ['tenant_id'], unique=False)
    op.create_index('ix_t_todo_tenant_id_created_by', 't_todo', ['tenant_id', 'created_by'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_t_todo_tenant_id_due_date', 't_todo', ['tenant_id', 'due_date'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_t_todo_tenant_id_status', 't_todo', ['tenant_id', 'status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))

    # --- ToDo アクティビティ(変更履歴) ---
    op.create_table('t_todo_activity',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('todo_id', sa.Uuid(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("action IN ('created', 'updated', 'status_changed', 'assignees_changed', 'visibility_changed', 'deleted')", name=op.f('t_todo_activity_action_check')),
    sa.ForeignKeyConstraint(['tenant_id', 'actor_id'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_activity_tenant_id_actor_id_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'todo_id'], ['t_todo.tenant_id', 't_todo.id'], name=op.f('t_todo_activity_tenant_id_todo_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_todo_activity_pkey')),
    comment='ToDo アクティビティ(変更履歴)'
    )
    op.create_index(op.f('ix_t_todo_activity_tenant_id'), 't_todo_activity', ['tenant_id'], unique=False)
    op.create_index('ix_t_todo_activity_tenant_id_todo_id_created_at', 't_todo_activity', ['tenant_id', 'todo_id', 'created_at'], unique=False)

    # --- ToDo の担当者 ---
    op.create_table('t_todo_assignee',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('todo_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('assigned_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'assigned_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_assignee_tenant_id_assigned_by_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'todo_id'], ['t_todo.tenant_id', 't_todo.id'], name=op.f('t_todo_assignee_tenant_id_todo_id_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_assignee_tenant_id_user_id_fkey')),
    sa.PrimaryKeyConstraint('tenant_id', 'todo_id', 'user_id', name=op.f('t_todo_assignee_pkey')),
    comment='ToDo の担当者'
    )
    op.create_index(op.f('ix_t_todo_assignee_tenant_id'), 't_todo_assignee', ['tenant_id'], unique=False)
    op.create_index('ix_t_todo_assignee_tenant_id_user_id', 't_todo_assignee', ['tenant_id', 'user_id'], unique=False)

    # --- ToDo の公開先組織 ---
    op.create_table('t_todo_organization',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('todo_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['t_organization.tenant_id', 't_organization.id'], name=op.f('t_todo_organization_tenant_id_organization_id_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'todo_id'], ['t_todo.tenant_id', 't_todo.id'], name=op.f('t_todo_organization_tenant_id_todo_id_fkey')),
    sa.PrimaryKeyConstraint('tenant_id', 'todo_id', 'organization_id', name=op.f('t_todo_organization_pkey')),
    comment='ToDo の公開先組織'
    )
    op.create_index(op.f('ix_t_todo_organization_tenant_id'), 't_todo_organization', ['tenant_id'], unique=False)
    op.create_index('ix_t_todo_organization_tenant_id_organization_id', 't_todo_organization', ['tenant_id', 'organization_id'], unique=False)

    # --- テナント分離の RLS(autogenerate は検出しない) ---
    for table_name in TENANT_SCOPED_TABLES:
        enable_tenant_rls(table_name)


def downgrade() -> None:
    """Downgrade schema.

    ToDo のテーブルを行ごと削除する(子テーブルから順に削除する)。
    """
    for table_name in reversed(TENANT_SCOPED_TABLES):
        disable_tenant_rls(table_name)

    op.drop_index('ix_t_todo_organization_tenant_id_organization_id', table_name='t_todo_organization')
    op.drop_index(op.f('ix_t_todo_organization_tenant_id'), table_name='t_todo_organization')
    op.drop_table('t_todo_organization')
    op.drop_index('ix_t_todo_assignee_tenant_id_user_id', table_name='t_todo_assignee')
    op.drop_index(op.f('ix_t_todo_assignee_tenant_id'), table_name='t_todo_assignee')
    op.drop_table('t_todo_assignee')
    op.drop_index('ix_t_todo_activity_tenant_id_todo_id_created_at', table_name='t_todo_activity')
    op.drop_index(op.f('ix_t_todo_activity_tenant_id'), table_name='t_todo_activity')
    op.drop_table('t_todo_activity')
    op.drop_index('ix_t_todo_tenant_id_status', table_name='t_todo', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_t_todo_tenant_id_due_date', table_name='t_todo', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_t_todo_tenant_id_created_by', table_name='t_todo', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_t_todo_tenant_id'), table_name='t_todo')
    op.drop_table('t_todo')
