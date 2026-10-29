"""create ap common tables

01 §9.4 の AP 共通テーブル(ユーザー・組織・組織メンバー・AP 監査ログ)を作成する。
モデルは main_app.models.ap_common。

- すべてテナントスコープのテーブル。tenant_id NOT NULL、参照される側に UNIQUE (tenant_id, id)、
  外部キーは (tenant_id, <列>) -> (tenant_id, id) の複合キー。
- RLS(ENABLE / FORCE + ポリシー tenant_isolation)は autogenerate が検出しないため手で追記している。
- t_ap_audit_log は追記のみ(03 §7)とするため、APP_DB_RUNTIME_USER のロールから UPDATE / DELETE を剥奪する。
  APP_DB_CP_AGENT_USER のロール(テナント物理削除)の SELECT / DELETE は initdb の DEFAULT PRIVILEGES で付与される。
- 実行時ロールのテーブル DML 権限は initdb の DEFAULT PRIVILEGES で自動付与される(GRANT は書かない)。

Revision ID: 0001
Revises:
Create Date: 2026-10-28 18:21:59.948095

"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 # autogenerate が sqlmodel.sql.sqltypes.AutoString を出力するため
from sqlalchemy.dialects import postgresql

from alembic import op
from modules.tenancy.rls import disable_tenant_rls, enable_tenant_rls

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 本リビジョンで作成するテナントスコープのテーブル(作成順。RLS の設定対象)
TENANT_SCOPED_TABLES = ("t_user", "t_organization", "t_organization_member", "t_ap_audit_log")


def _role_identifier(env_name: str) -> str:
    """ 環境変数のロール名を SQL 識別子としてクォートして返す(ロール名はハードコードしない) """
    role = os.environ.get(env_name)
    if not role:
        raise RuntimeError(f"環境変数 {env_name} が設定されていません")
    return postgresql.dialect().identifier_preparer.quote_identifier(role)


def upgrade() -> None:
    """Upgrade schema."""
    runtime = _role_identifier("APP_DB_RUNTIME_USER")

    # --- ユーザー ---
    op.create_table('t_user',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('idp_subject', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('display_name', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('t_user_version_positive_check')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_user_tenant_id_created_by_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'updated_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_user_tenant_id_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_user_pkey')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('t_user_tenant_id_id_key')),
    sa.UniqueConstraint('tenant_id', 'idp_subject', name=op.f('t_user_tenant_id_idp_subject_key')),
    comment='ユーザー(テナント内)'
    )
    op.create_index(op.f('ix_t_user_tenant_id'), 't_user', ['tenant_id'], unique=False)
    # メールアドレスはテナント内で大文字小文字を区別せず一意(01 PF-USR-06)
    op.create_index('t_user_tenant_id_lower_email_key', 't_user', ['tenant_id', sa.literal_column('lower(email)')], unique=True)

    # --- 組織(論理削除) ---
    op.create_table('t_organization',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('version >= 1', name=op.f('t_organization_version_positive_check')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_organization_tenant_id_created_by_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'updated_by'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_organization_tenant_id_updated_by_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_organization_pkey')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('t_organization_tenant_id_id_key')),
    comment='組織(テナント内。論理削除)'
    )
    op.create_index(op.f('ix_t_organization_tenant_id'), 't_organization', ['tenant_id'], unique=False)
    # 組織名は有効な組織の中でテナント内一意(論理削除のため部分インデックス。03 §5.1)
    op.create_index('t_organization_tenant_id_lower_name_key', 't_organization', ['tenant_id', sa.literal_column('lower(name)')], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))

    # --- 組織メンバー ---
    op.create_table('t_organization_member',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['t_organization.tenant_id', 't_organization.id'], name=op.f('t_organization_member_tenant_id_organization_id_fkey')),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['t_user.tenant_id', 't_user.id'], name=op.f('t_organization_member_tenant_id_user_id_fkey')),
    sa.PrimaryKeyConstraint('tenant_id', 'organization_id', 'user_id', name=op.f('t_organization_member_pkey')),
    comment='組織メンバー'
    )
    op.create_index(op.f('ix_t_organization_member_tenant_id'), 't_organization_member', ['tenant_id'], unique=False)
    op.create_index('ix_t_organization_member_tenant_id_user_id', 't_organization_member', ['tenant_id', 'user_id'], unique=False)

    # --- AP 監査ログ(追記のみ) ---
    op.create_table('t_ap_audit_log',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('target_type', sa.Text(), nullable=True),
    sa.Column('target_id', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('request_id', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('t_ap_audit_log_pkey')),
    comment='AP 監査ログ(追記のみ)'
    )
    op.create_index(op.f('ix_t_ap_audit_log_tenant_id'), 't_ap_audit_log', ['tenant_id'], unique=False)
    op.create_index('ix_t_ap_audit_log_tenant_id_created_at', 't_ap_audit_log', ['tenant_id', 'created_at'], unique=False)
    op.create_index('ix_t_ap_audit_log_tenant_id_target_type_target_id', 't_ap_audit_log', ['tenant_id', 'target_type', 'target_id'], unique=False)
    # DEFAULT PRIVILEGES で付与された UPDATE / DELETE を剥奪し、実行時ロールからは追記のみとする(03 §7)。
    # 物理削除は app_cp_agent(テナント物理削除)だけが行う
    op.execute(f"REVOKE UPDATE, DELETE ON t_ap_audit_log FROM {runtime}")

    # --- テナント分離の RLS(autogenerate は検出しない) ---
    for table_name in TENANT_SCOPED_TABLES:
        enable_tenant_rls(table_name)


def downgrade() -> None:
    """Downgrade schema.

    AP 共通テーブルを行ごと削除する(ToDo 等のテーブルは 0002 の downgrade で先に削除されている前提)。
    """
    for table_name in reversed(TENANT_SCOPED_TABLES):
        disable_tenant_rls(table_name)

    # 権限はテーブルと共に消えるため、REVOKE の取り消しは不要
    op.drop_index('ix_t_ap_audit_log_tenant_id_target_type_target_id', table_name='t_ap_audit_log')
    op.drop_index('ix_t_ap_audit_log_tenant_id_created_at', table_name='t_ap_audit_log')
    op.drop_index(op.f('ix_t_ap_audit_log_tenant_id'), table_name='t_ap_audit_log')
    op.drop_table('t_ap_audit_log')
    op.drop_index('ix_t_organization_member_tenant_id_user_id', table_name='t_organization_member')
    op.drop_index(op.f('ix_t_organization_member_tenant_id'), table_name='t_organization_member')
    op.drop_table('t_organization_member')
    op.drop_index('t_organization_tenant_id_lower_name_key', table_name='t_organization', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_t_organization_tenant_id'), table_name='t_organization')
    op.drop_table('t_organization')
    op.drop_index('t_user_tenant_id_lower_email_key', table_name='t_user')
    op.drop_index(op.f('ix_t_user_tenant_id'), table_name='t_user')
    op.drop_table('t_user')
