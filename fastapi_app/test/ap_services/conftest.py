# -*- coding: utf-8 -*-
"""AP のサービス層(ユーザー同期・ユーザー管理・組織管理)と、それを使う API のテスト用フィクスチャ。

- DB は開発 DB の ``app_db``(``app_runtime`` で書き込み、RLS 適用)。**テストごとに使い捨てのテナント ID(ランダムな UUID)を使い、
  alpha / beta のデータには触れない**。後片付けは ``app_cp_agent``(``AppTenantDataRepository`` = 監査ログを含む全テーブルの物理削除)で行う。
  接続できない・ロールが無い場合は skip する(``tenancy/conftest.py`` のエンジンのフィクスチャ)。
- Keycloak は ``TenantRealmIdp``(``httpx.MockTransport`` の状態を持つフェイク)。``kc_admin_factory`` に ``idp.factory`` を渡す。
- 接続情報は環境変数から読む(``.env`` は読まない)。

提供するフィクスチャ:
    - ``ap_db``: テナント・ユーザー・組織の準備、コミット済みの内容の参照、後片付け(``ApDb``)
    - ``idp``: テナントレルムの Keycloak のフェイク
    - ``tenant_a`` / ``tenant_b`` は ``tenancy/conftest.py`` のもの(DB には存在しない ID。``ap_db.tenant()`` で使い捨てのテナントを作る)
"""
import datetime as dt
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session
from tenancy.conftest import _tenant_context_is_clean, app_cp_agent_engine, app_owner_engine, app_runtime_engine  # noqa: F401

from control_plane_app.repositories.app_tenant_data import AppTenantDataRepository
from main_app.models import TOrganization, TOrganizationMember, TTodo, TUser
from modules.tenancy.context import TenantContext, tenant_scope
from modules.tenancy.db import install_tenant_guc_listener, uninstall_tenant_guc_listener

from .fake_idp import TenantRealmIdp

__all__ = ["ApDb", "TenantRealmIdp", "_tenant_context_is_clean", "ap_db", "app_cp_agent_engine", "app_owner_engine", "app_runtime_engine", "idp"]


# 後片付けの確認で数えるテーブル
CLEANED_TABLES = ("t_user", "t_organization", "t_organization_member", "t_ap_audit_log", "t_todo", "t_todo_assignee", "t_todo_organization", "t_todo_activity", "t_todo_comment", "t_todo_checklist_item")


class ApDb:
    """app_db(開発 DB)の補助。使い捨てのテナントを作り、終了時に監査ログを含む全データを物理削除する。

    テナントの ``tenant_id`` は AP のテーブルにしか現れない(CP 側の台帳は不要)。API のテストで台帳の行が必要な場合は、
    ``cp_db.insert_tenant()`` の ID を ``track()`` で渡す。
    """

    def __init__(self, runtime: Engine, agent: Engine) -> None:
        self.runtime = runtime
        self.agent = agent
        self.maker = sessionmaker(bind=runtime, class_=Session)
        install_tenant_guc_listener(self.maker)
        self.tenant_ids: list[uuid.UUID] = []

    # -- テナント -------------------------------------------------------------
    def tenant(self, *, user_id: uuid.UUID | None = None) -> TenantContext:
        """使い捨てのテナントのコンテキストを作る(後片付けの対象になる)。"""
        tenant_id = uuid.uuid7()
        self.tenant_ids.append(tenant_id)
        return TenantContext(tenant_id=tenant_id, tenant_code=f"zt-{tenant_id.hex[-10:]}", user_id=user_id, plane="app")

    def track(self, tenant_id: uuid.UUID) -> None:
        """後片付けの対象のテナント ID を追加する(台帳に作った使い捨てテナントなど)。"""
        if tenant_id not in self.tenant_ids:
            self.tenant_ids.append(tenant_id)

    @contextmanager
    def session(self, ctx: TenantContext) -> Iterator[Session]:
        """テナントコンテキストを設定して ``app_runtime`` のセッションを開く(サービスに渡す。コミットはサービスが行う)。"""
        with tenant_scope(ctx), self.maker() as session:
            yield session

    # -- 準備(コミット済みの行を作る) --------------------------------------------
    def add_user(
        self,
        ctx: TenantContext,
        *,
        sub: str | None = None,
        email: str | None = None,
        display_name: str = "Test User",
        is_active: bool = True,
        version: int = 1,
    ) -> TUser:
        """ユーザー行を直接作る(切り離した値を返す)。``sub`` を省略すると UUID の文字列にする。"""
        sub = sub or str(uuid.uuid4())
        with self.session(ctx) as session:
            user = TUser(tenant_id=ctx.tenant_id, idp_subject=sub, email=email, display_name=display_name, is_active=is_active, version=version)
            session.add(user)
            session.commit()
            session.refresh(user)
            session.expunge(user)
        return user

    def add_org(self, ctx: TenantContext, name: str, *, deleted: bool = False, members: tuple[uuid.UUID, ...] = ()) -> TOrganization:
        """組織行(と所属)を直接作る(切り離した値を返す)。"""
        with self.session(ctx) as session:
            org = TOrganization(tenant_id=ctx.tenant_id, name=name)
            if deleted:
                org.deleted_at = dt.datetime.now(dt.UTC)
            session.add(org)
            session.flush()
            for user_id in members:
                session.add(TOrganizationMember(tenant_id=ctx.tenant_id, organization_id=org.id, user_id=user_id))
            session.commit()
            session.refresh(org)
            session.expunge(org)
        return org

    def add_todo(self, ctx: TenantContext, user_id: uuid.UUID, *, status: str = "open", title: str = "todo", deleted: bool = False) -> uuid.UUID:
        """ToDo の行を直接作る(メトリクスの集計の準備。論理削除済みも作れる)。ID を返す。"""
        with self.session(ctx) as session:
            todo = TTodo(tenant_id=ctx.tenant_id, created_by=user_id, updated_by=user_id, title=title, status=status)
            if deleted:
                todo.deleted_at = dt.datetime.now(dt.UTC)
            session.add(todo)
            session.commit()
            return todo.id

    # -- 参照(別のセッションで、コミット済みの内容を読む) --------------------------
    def rows(self, ctx: TenantContext, sql: str, **params: Any) -> list[dict[str, Any]]:
        """``ctx`` のテナントとして SQL(SELECT)を実行し、行を辞書で返す。"""
        with self.session(ctx) as session:
            return [dict(row) for row in session.connection().execute(text(sql), params).mappings().all()]

    def users(self, ctx: TenantContext) -> list[dict[str, Any]]:
        return self.rows(ctx, "SELECT * FROM t_user ORDER BY created_at, id")

    def user(self, ctx: TenantContext, user_id: uuid.UUID) -> dict[str, Any] | None:
        found = self.rows(ctx, "SELECT * FROM t_user WHERE id = :id", id=user_id)
        return found[0] if found else None

    def orgs(self, ctx: TenantContext, *, include_deleted: bool = True) -> list[dict[str, Any]]:
        where = "" if include_deleted else "WHERE deleted_at IS NULL"
        return self.rows(ctx, f"SELECT * FROM t_organization {where} ORDER BY created_at, id")

    def members(self, ctx: TenantContext, org_id: uuid.UUID) -> list[uuid.UUID]:
        return [row["user_id"] for row in self.rows(ctx, "SELECT user_id FROM t_organization_member WHERE organization_id = :id ORDER BY user_id", id=org_id)]

    def audits(self, ctx: TenantContext, action: str | None = None) -> list[dict[str, Any]]:
        rows = self.rows(ctx, "SELECT * FROM t_ap_audit_log ORDER BY created_at, id")
        return [row for row in rows if action is None or row["action"] == action]

    def dump(self, ctx: TenantContext) -> str:
        """テナントの AP のデータ(ユーザー・組織・所属・監査ログ)全体を 1 つの文字列にする(秘匿値が残っていないことの確認用)。"""
        return repr([self.users(ctx), self.orgs(ctx), self.audits(ctx), self.rows(ctx, "SELECT * FROM t_organization_member")])

    def count(self, tenant_id: uuid.UUID, table: str) -> int:
        """``app_cp_agent``(RLS 適用)で、テナントの行数を数える(後片付けの確認用)。"""
        from modules.tenancy.db import tenant_guc_scope

        with Session(self.agent) as session:
            try:
                with tenant_guc_scope(session, tenant_id):
                    return int(session.connection().execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            finally:
                session.rollback()

    # -- 後片付け -------------------------------------------------------------
    def cleanup(self) -> None:
        """記録したテナントのデータを、監査ログを含めて物理削除する(``app_cp_agent``)。"""
        repository = AppTenantDataRepository(engine_factory=lambda: self.agent)
        try:
            for tenant_id in self.tenant_ids:
                repository.purge_tenant_data(tenant_id)
        finally:
            uninstall_tenant_guc_listener(self.maker)
        leftovers = {(str(tenant_id), table): self.count(tenant_id, table) for tenant_id in self.tenant_ids for table in CLEANED_TABLES}
        assert not any(leftovers.values()), f"後片付けの後に app_db にテストの行が残っている: { {k: v for k, v in leftovers.items() if v} }"


@pytest.fixture
def ap_db(app_runtime_engine, app_cp_agent_engine) -> Iterator[ApDb]:  # noqa: F811
    """app_db の補助。テスト終了時に、使い捨てテナントのデータをすべて削除する。"""
    db = ApDb(app_runtime_engine, app_cp_agent_engine)
    try:
        yield db
    finally:
        db.cleanup()


@pytest.fixture
def idp() -> TenantRealmIdp:
    """テナントレルムの Keycloak のフェイク。"""
    return TenantRealmIdp()
