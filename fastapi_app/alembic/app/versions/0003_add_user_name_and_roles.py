"""add user name and roles

t_user に、Keycloak を正とする一覧表示用の写し(姓・名・ロール)を追加する。モデルは main_app.models.ap_common.TUser。
仕様は docs/architecture/01-platform-concepts.md §9.4、02-platform-implementation.md §4.7、05-decisions.md #33。

- first_name / last_name: text NULL。
- roles: text[] NOT NULL DEFAULT '{}'。要素は tenant_admin / member のみ(CHECK 制約 t_user_roles_check)。
  CHECK 制約は autogenerate が検出しないため手で追記している。値はモデルを import せずリテラルで持つ。
- 既存の行は roles = '{}'、姓名 = NULL のまま(次回ログインの同期で埋まる)。
- 既存の RLS(tenant_isolation)と権限は列追加の影響を受けないため、ここでは触らない。

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29 06:52:17.731295

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('t_user', sa.Column('first_name', sa.Text(), nullable=True))
    op.add_column('t_user', sa.Column('last_name', sa.Text(), nullable=True))
    op.add_column('t_user', sa.Column('roles', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False))
    op.create_check_constraint(op.f('t_user_roles_check'), 't_user', "roles <@ ARRAY['tenant_admin', 'member']::text[]")


def downgrade() -> None:
    """Downgrade schema.

    追加した列(と CHECK 制約)を削除する。写しの値は失われるが、Keycloak が正のため次回ログインの同期で復元できる。
    """
    op.drop_constraint(op.f('t_user_roles_check'), 't_user', type_='check')
    op.drop_column('t_user', 'roles')
    op.drop_column('t_user', 'last_name')
    op.drop_column('t_user', 'first_name')
