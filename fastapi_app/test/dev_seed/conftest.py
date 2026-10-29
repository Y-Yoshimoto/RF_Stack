# -*- coding: utf-8 -*-
"""dev_tools.seed_todos(開発用の ToDo シード。開発専用)のテスト用フィクスチャ。

**開発 DB の alpha / beta に書き込まない・外部の Keycloak に接続しない**ための分離:

- AP は使い捨てのテナント(``ap_db.tenant()``)に対して ``seed_tenant_todos()`` を呼ぶ(``tenant_code`` だけを alpha / beta にして ToDo の定義を選ぶ。
  台帳の alpha / beta の行も、その AP のデータも使わない)。後片付けは ``ap_db`` が行う。
- Keycloak は ``TenantRealmIdp`` のフェイク。``tenant-alpha`` / ``tenant-beta`` のレルムにシードのユーザー(``DEV_TENANT_USERS``)を作り、
  ``_fetch_idp_users`` が呼ぶ ``create_provisioner_admin_client`` をフェイクの管理クライアントに差し替える。
- 環境は ``APP_ENV=development`` に固定する(個別のテストで上書きする)。

提供するフィクスチャ: ``seed_env``(``SeedEnv``)。
"""
import datetime as dt
from dataclasses import dataclass

import pytest
from ap_services.conftest import ApDb, ap_db, app_cp_agent_engine, app_owner_engine, app_runtime_engine, idp  # noqa: F401

from dev_tools import seed_todos
from modules.auth.dev_profiles import DEV_TENANT_USERS, DevTenant
from modules.tenancy.context import TenantContext

__all__ = ["SeedEnv", "beta_env", "ap_db", "app_cp_agent_engine", "app_owner_engine", "app_runtime_engine", "idp", "seed_env"]

TODAY = dt.date(2030, 6, 15)


@dataclass
class SeedEnv:
    """使い捨てのテナントとフェイクの IdP。"""

    ap_db: ApDb
    idp: object
    tenant: DevTenant
    ctx: TenantContext

    def idp_users(self) -> dict[str, seed_todos._IdpUser]:
        """フェイクの IdP から引いたシードのユーザー(``_fetch_idp_users`` と同じ経路)。"""
        return seed_todos._fetch_idp_users(self.tenant)

    def run(self, *, today: dt.date = TODAY) -> seed_todos.SeedTodosResult:
        """``seed_tenant_todos`` を 1 回実行する。"""
        with self.ap_db.session(self.ctx) as session:
            return seed_todos.seed_tenant_todos(session, self.tenant, self.ctx.tenant_id, self.idp_users(), today=today)

    def rows(self, sql: str, **params):
        return self.ap_db.rows(self.ctx, sql, **params)

    def counts(self) -> dict[str, int]:
        tables = ("t_user", "t_organization", "t_organization_member", "t_todo", "t_todo_assignee", "t_todo_organization", "t_todo_activity", "t_todo_comment", "t_todo_checklist_item", "t_ap_audit_log")
        return {table: len(self.rows(f"SELECT 1 FROM {table}")) for table in tables}


def make_env(ap_db: ApDb, idp, monkeypatch, tenant_code: str) -> SeedEnv:  # noqa: F811
    tenant = DevTenant(tenant_code=tenant_code, display_name=tenant_code.title())
    for user in DEV_TENANT_USERS[tenant_code]:
        idp.seed_user(tenant.realm_name, username=user.username, email=user.email, first_name=user.first_name, last_name=user.last_name, roles=user.roles)
    monkeypatch.setattr(seed_todos, "create_provisioner_admin_client", idp.admin)
    ctx = ap_db.tenant()
    return SeedEnv(ap_db=ap_db, idp=idp, tenant=tenant, ctx=ctx)


@pytest.fixture(autouse=True)
def _development(monkeypatch) -> None:
    """既定は開発環境(``APP_ENV=development``)。"""
    monkeypatch.setenv("APP_ENV", "development")


@pytest.fixture
def seed_env(ap_db, idp, monkeypatch) -> SeedEnv:  # noqa: F811
    """alpha の定義でシードする使い捨てのテナント。"""
    return make_env(ap_db, idp, monkeypatch, "alpha")


@pytest.fixture
def beta_env(ap_db, idp, monkeypatch) -> SeedEnv:  # noqa: F811
    """beta の定義でシードする使い捨てのテナント。"""
    return make_env(ap_db, idp, monkeypatch, "beta")

