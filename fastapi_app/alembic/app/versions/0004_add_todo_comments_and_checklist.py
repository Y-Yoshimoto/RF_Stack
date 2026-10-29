"""add todo comments and checklist

ToDo のコメントとチェックリスト(ToDoApp.md §4.5・§4.6・§5・§9.1)を追加する。モデルは main_app.models.todo。

- t_todo_comment: コメント。論理削除(deleted_at)・楽観ロック(version)。一覧用に
  (tenant_id, todo_id, created_at, id) の部分インデックス(deleted_at IS NULL)。本文は 1〜4000 文字の CHECK。
- t_todo_checklist_item: チェックリスト項目。物理削除・楽観ロック。
  UNIQUE (tenant_id, todo_id, position) は DEFERRABLE INITIALLY DEFERRED(1 トランザクションで position を入れ替えるため)。
  CHECK: 項目名 1〜200 文字、position >= 0、完了の整合性(is_done なら done_at / done_by が NOT NULL、そうでなければ両方 NULL)。
- t_todo.checklist_version: int NOT NULL DEFAULT 1(CHECK >= 1)。既存の行は 1 になる。
- t_todo_activity の action の CHECK に 'checklist_changed' を加える(autogenerate は CHECK を検出しないため手で張り替える)。
- 2 つの新テーブルは tenant_id NOT NULL・複合外部キー・RLS(autogenerate は RLS を検出しないため手で追記)。
- CHECK の値はモデルを import せずリテラルで持つ(後からモデルが変わっても本リビジョンの意味を変えないため)。

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29 18:50:03.169671

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 # autogenerate が sqlmodel.sql.sqltypes.AutoString を出力するため

from alembic import op
from modules.tenancy.rls import disable_tenant_rls, enable_tenant_rls

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 本リビジョンで作成するテナントスコープのテーブル(作成順。RLS の設定対象)
TENANT_SCOPED_TABLES = ("t_todo_checklist_item", "t_todo_comment")

# t_todo_activity.action の許可値(0002 時点 / 0004 時点)
ACTIVITY_ACTION_CHECK_BEFORE = "action IN ('created', 'updated', 'status_changed', 'assignees_changed', 'visibility_changed', 'deleted')"
ACTIVITY_ACTION_CHECK_AFTER = "action IN ('created', 'updated', 'status_changed', 'assignees_changed', 'visibility_changed', 'deleted', 'checklist_changed')"


def upgrade() -> None:
    """Upgrade schema."""
    # --- チェックリスト項目(物理削除・楽観ロック) ---
    op.create_table('t_todo_checklist_item',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('todo_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('is_done', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('done_by', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint('(is_done AND done_at IS NOT NULL AND done_by IS NOT NULL) OR (NOT is_done AND done_at IS NULL AND done_by IS NULL)', name=op.f('t_todo_checklist_item_done_consistent_check')),
    sa.CheckConstraint('char_length(title) BETWEEN 1 AND 200', name=op.f('t_todo_checklist_item_title_length_check')),
    sa.CheckConstraint('position >= 0', name=op.f('t_todo_checklist_item_position_non_negative_check')),
    sa.CheckConstraint('version >= 1', name=op.f('t_todo_checklist_item_version_positive_check')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_checklist_item_tenant_id_created_by_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'done_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_checklist_item_tenant_id_done_by_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'todo_id'], ['t_todo.tenant_id', 't_todo.id'], name=op.f('t_todo_checklist_item_tenant_id_todo_id_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'updated_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_checklist_item_tenant_id_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_todo_checklist_item_pkey')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('t_todo_checklist_item_tenant_id_id_key')),
    sa.UniqueConstraint('tenant_id', 'todo_id', 'position', deferrable=True, initially='DEFERRED', name=op.f('t_todo_checklist_item_tenant_id_todo_id_position_key')),
    comment='ToDo のチェックリスト項目(物理削除・楽観ロック)'
    )
    op.create_index(op.f('ix_t_todo_checklist_item_tenant_id'), 't_todo_checklist_item', ['tenant_id'], unique=False)
    # --- コメント(論理削除・楽観ロック) ---
    op.create_table('t_todo_comment',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('todo_id', sa.Uuid(), nullable=False),
    sa.Column('author_id', sa.Uuid(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('char_length(body) BETWEEN 1 AND 4000', name=op.f('t_todo_comment_body_length_check')),
    sa.CheckConstraint('version >= 1', name=op.f('t_todo_comment_version_positive_check')),
    sa.ForeignKeyConstraint(['tenant_id', 'author_id'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_todo_comment_tenant_id_author_id_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'todo_id'], ['t_todo.tenant_id', 't_todo.id'], name=op.f('t_todo_comment_tenant_id_todo_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_todo_comment_pkey')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('t_todo_comment_tenant_id_id_key')),
    comment='ToDo のコメント(論理削除・楽観ロック)'
    )
    op.create_index(op.f('ix_t_todo_comment_tenant_id'), 't_todo_comment', ['tenant_id'], unique=False)
    op.create_index('ix_t_todo_comment_tenant_id_todo_id_created_at_id', 't_todo_comment', ['tenant_id', 'todo_id', 'created_at', 'id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))

    # --- ToDo にチェックリスト全体の版を追加(既存の行は 1) ---
    op.add_column('t_todo', sa.Column('checklist_version', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.create_check_constraint(op.f('t_todo_checklist_version_positive_check'), 't_todo', 'checklist_version >= 1')

    # --- アクティビティの種別に checklist_changed を追加(CHECK の張り替え) ---
    op.drop_constraint(op.f('t_todo_activity_action_check'), 't_todo_activity', type_='check')
    op.create_check_constraint(op.f('t_todo_activity_action_check'), 't_todo_activity', ACTIVITY_ACTION_CHECK_AFTER)

    # --- テナント分離の RLS(autogenerate は検出しない) ---
    for table_name in TENANT_SCOPED_TABLES:
        enable_tenant_rls(table_name)


def downgrade() -> None:
    """Downgrade schema.

    データを失う操作を含む。
    - t_todo_activity の action = 'checklist_changed' の行を削除してから CHECK を元に戻す(残すと CHECK 違反になるため)。
    - t_todo_comment / t_todo_checklist_item を行ごと削除する(RLS を解除してからテーブルを削除)。
    - t_todo.checklist_version 列を削除する。
    """
    # アクティビティ: 新しい種別の行を消してから CHECK を戻す(行を残したままでは戻せない)
    op.execute("DELETE FROM t_todo_activity WHERE action = 'checklist_changed'")
    op.drop_constraint(op.f('t_todo_activity_action_check'), 't_todo_activity', type_='check')
    op.create_check_constraint(op.f('t_todo_activity_action_check'), 't_todo_activity', ACTIVITY_ACTION_CHECK_BEFORE)

    # t_todo.checklist_version
    op.drop_constraint(op.f('t_todo_checklist_version_positive_check'), 't_todo', type_='check')
    op.drop_column('t_todo', 'checklist_version')

    # 新しいテーブル(RLS を解除してから削除)
    for table_name in reversed(TENANT_SCOPED_TABLES):
        disable_tenant_rls(table_name)
    op.drop_index('ix_t_todo_comment_tenant_id_todo_id_created_at_id', table_name='t_todo_comment', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_t_todo_comment_tenant_id'), table_name='t_todo_comment')
    op.drop_table('t_todo_comment')
    op.drop_index(op.f('ix_t_todo_checklist_item_tenant_id'), table_name='t_todo_checklist_item')
    op.drop_table('t_todo_checklist_item')
