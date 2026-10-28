"""revise cp tables and add tenant registry view

01 §9.5 に沿ってコントロールプレーンのテーブルを整備する。

- t_tenant を改訂する(id を uuid/UUIDv7 に変更、tenant_code / status / realm_name 等を追加、旧列を削除)。
  id の型変更と NOT NULL 列の追加を伴うため、ALTER ではなく**作り直す**。
  既存行があると失われるため、t_tenant に行がある場合は中断する(開発 DB は空の前提)。
- t_provisioning_history / t_tenant_daily_metric / t_scheduled_job_run / t_cp_audit_log を追加する。
- テナントレジストリ公開ビュー v_tenant_registry を作成し、SELECT を CP_DB_REGISTRY_READER_USER のロールにだけ付与する。
- t_cp_audit_log は追記のみとするため、CP_DB_RUNTIME_USER のロールから UPDATE / DELETE を剥奪する。

autogenerate はビュー・GRANT/REVOKE・既存テーブルへの CHECK 制約を検出しないため、本リビジョンは手で書いている。
制約値はモデル(control_plane_app.models.sql_models)を import せずリテラルで持つ(後からモデルが変わっても本リビジョンの意味を変えないため)。
実行時ロール(cp_runtime)のテーブル DML 権限は initdb の DEFAULT PRIVILEGES で自動付与される。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 08:52:42.880356

"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401 # autogenerate が sqlmodel.sql.sqltypes.AutoString を出力するため
from sqlalchemy.dialects import postgresql

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# テナントの状態(01 §6.1)
TENANT_STATUS_CHECK = "status IN ('PROVISIONING', 'ACTIVE', 'FAILED', 'SUSPENDED', 'PENDING_DELETION', 'DEPROVISIONING', 'DELETED')"
# テナントコードの形式(01 §5.1)
TENANT_CODE_CHECK = "tenant_code ~ '^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}$'"
# 払い出し・定期ジョブの実行状態
RUN_STATUS_CHECK = "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')"

REGISTRY_VIEW = "v_tenant_registry"
# DELETED のテナントは公開しない(存在しないテナントと区別しない。01 §10.2)
REGISTRY_VIEW_SQL = f"""
CREATE VIEW {REGISTRY_VIEW} AS
SELECT
    id AS tenant_id,
    tenant_code,
    realm_name,
    status
FROM t_tenant
WHERE status <> 'DELETED'
"""


def _role_identifier(env_name: str) -> str:
    """ 環境変数のロール名を SQL 識別子としてクォートして返す(ロール名はハードコードしない) """
    role = os.environ.get(env_name)
    if not role:
        raise RuntimeError(f"環境変数 {env_name} が設定されていません")
    return postgresql.dialect().identifier_preparer.quote_identifier(role)


def _abort_if_tenants_exist(direction: str) -> None:
    """ t_tenant を作り直すため、行がある場合は中断する(オフラインモードでは確認できないため省略) """
    if context.is_offline_mode():
        return
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM t_tenant")).scalar_one()
    if count:
        raise RuntimeError(f"t_tenant に {count} 行あるため {direction} を中断しました。t_tenant は作り直すため、既存行は失われます。データを退避・削除してから再実行してください")


def upgrade() -> None:
    """Upgrade schema."""
    _abort_if_tenants_exist("upgrade")
    registry_reader = _role_identifier("CP_DB_REGISTRY_READER_USER")
    runtime = _role_identifier("CP_DB_RUNTIME_USER")

    # --- t_tenant を作り直す(0001 の定義を削除) ---
    op.drop_index(op.f('ix_t_tenant_name'), table_name='t_tenant')
    op.drop_index(op.f('ix_t_tenant_id'), table_name='t_tenant')
    op.drop_table('t_tenant')
    op.create_table('t_tenant',
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('tenant_code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='PROVISIONING', nullable=False),
    sa.Column('realm_name', sa.Text(), nullable=False),
    sa.Column('tier', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('deletion_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(TENANT_STATUS_CHECK, name=op.f('t_tenant_status_check')),
    sa.CheckConstraint(TENANT_CODE_CHECK, name=op.f('t_tenant_tenant_code_format_check')),
    sa.CheckConstraint('version >= 1', name=op.f('t_tenant_version_positive_check')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_tenant_pkey')),
    sa.UniqueConstraint('tenant_code', name=op.f('t_tenant_tenant_code_key')),
    sa.UniqueConstraint('realm_name', name=op.f('t_tenant_realm_name_key')),
    comment='テナント台帳'
    )

    # --- 払い出し履歴 ---
    op.create_table('t_provisioning_history',
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='RUNNING', nullable=False),
    sa.Column('step', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint(RUN_STATUS_CHECK, name=op.f('t_provisioning_history_status_check')),
    sa.CheckConstraint("type IN ('onboard', 'offboard')", name=op.f('t_provisioning_history_type_check')),
    sa.ForeignKeyConstraint(['tenant_id'], ['t_tenant.id'], name=op.f('t_provisioning_history_tenant_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_provisioning_history_pkey')),
    comment='払い出し履歴'
    )
    op.create_index('ix_t_provisioning_history_tenant_id_started_at', 't_provisioning_history', ['tenant_id', 'started_at'], unique=False)

    # --- 日次メトリクス(縦持ち) ---
    op.create_table('t_tenant_daily_metric',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('metric_key', sa.Text(), nullable=False),
    sa.Column('value', sa.Numeric(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['t_tenant.id'], name=op.f('t_tenant_daily_metric_tenant_id_fkey')),
    sa.PrimaryKeyConstraint('tenant_id', 'date', 'metric_key', name=op.f('t_tenant_daily_metric_pkey')),
    comment='テナント日次メトリクス(縦持ち)'
    )
    op.create_index('ix_t_tenant_daily_metric_date_metric_key', 't_tenant_daily_metric', ['date', 'metric_key'], unique=False)

    # --- 定期ジョブ実行履歴 ---
    op.create_table('t_scheduled_job_run',
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('job_name', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='RUNNING', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint(RUN_STATUS_CHECK, name=op.f('t_scheduled_job_run_status_check')),
    sa.PrimaryKeyConstraint('id', name=op.f('t_scheduled_job_run_pkey')),
    comment='定期ジョブ実行履歴'
    )
    op.create_index('ix_t_scheduled_job_run_job_name_started_at', 't_scheduled_job_run', ['job_name', 'started_at'], unique=False)

    # --- CP 監査ログ(追記のみ) ---
    op.create_table('t_cp_audit_log',
    sa.Column('id', sa.Uuid(), server_default=sa.text('uuidv7()'), nullable=False),
    sa.Column('actor', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('target_tenant_id', sa.Uuid(), nullable=True),
    sa.Column('target_type', sa.Text(), nullable=True),
    sa.Column('target_id', sa.Text(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('request_id', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('t_cp_audit_log_pkey')),
    comment='CP 監査ログ(追記のみ)'
    )
    op.create_index('ix_t_cp_audit_log_target_tenant_id_created_at', 't_cp_audit_log', ['target_tenant_id', 'created_at'], unique=False)
    # DEFAULT PRIVILEGES で付与された UPDATE / DELETE を剥奪し、実行時ロールからは追記のみとする(03 §7)
    op.execute(f"REVOKE UPDATE, DELETE ON t_cp_audit_log FROM {runtime}")

    # --- テナントレジストリ公開ビュー ---
    # 所有者(cp_owner)の権限で t_tenant を読む通常のビュー(security_invoker を付けない)。
    # cp_registry_reader には t_tenant の権限を与えず、ビューの SELECT だけを付与する。
    op.execute(REGISTRY_VIEW_SQL)
    op.execute(f"COMMENT ON VIEW {REGISTRY_VIEW} IS 'テナントレジストリ公開ビュー(AP からの参照用。DELETED を除く)'")
    op.execute(f"GRANT SELECT ON {REGISTRY_VIEW} TO {registry_reader}")


def downgrade() -> None:
    """Downgrade schema.

    0002 で追加したテーブル(払い出し履歴・メトリクス・ジョブ履歴・CP 監査ログ)は行ごと削除される。
    t_tenant は 0001 の定義で作り直すため、行がある場合は中断する。
    """
    _abort_if_tenants_exist("downgrade")

    # ビューを先に削除する(t_tenant に依存しているため)。GRANT もビューと共に消える
    op.execute(f"DROP VIEW {REGISTRY_VIEW}")

    op.drop_index('ix_t_cp_audit_log_target_tenant_id_created_at', table_name='t_cp_audit_log')
    op.drop_table('t_cp_audit_log')
    op.drop_index('ix_t_scheduled_job_run_job_name_started_at', table_name='t_scheduled_job_run')
    op.drop_table('t_scheduled_job_run')
    op.drop_index('ix_t_tenant_daily_metric_date_metric_key', table_name='t_tenant_daily_metric')
    op.drop_table('t_tenant_daily_metric')
    op.drop_index('ix_t_provisioning_history_tenant_id_started_at', table_name='t_provisioning_history')
    op.drop_table('t_provisioning_history')

    # t_tenant を 0001 の定義に戻す
    op.drop_table('t_tenant')
    op.create_table('t_tenant',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('isenabled', sa.Boolean(), nullable=False),
    sa.Column('claim', sa.Boolean(), nullable=False),
    sa.Column('external_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('industry', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('t_tenant_pkey')),
    comment='テナント情報テーブル'
    )
    op.create_index(op.f('ix_t_tenant_id'), 't_tenant', ['id'], unique=True)
    op.create_index(op.f('ix_t_tenant_name'), 't_tenant', ['name'], unique=False)
