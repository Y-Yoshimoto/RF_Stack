#!/usr/bin/env python
# coding:utf-8
"""``GET /api/v1/me``（自分のプロフィール。01 §10.2、§7.5）。

認証・テナント判定（AP セッション、ACTIVE なテナント）・CSRF 対策・ユーザーの有効確認は ``main_app.route.v1.apiapp`` のルーターで適用済み。
テナントはコンテキスト（セッション → レジストリ照合）から、ユーザーはセッションと AP のユーザー行から得る。リクエストの値は使わない。
``user.id`` は AP のユーザー ID（``t_user.id``）で、``GET /api/v1/users`` の ``id`` ・組織のメンバー ID と同じ値（IdP の ``sub`` ではない）。
"""
from fastapi import APIRouter

from main_app.route.v1.api_me.schemas import MeOrganization, MeRead, MeTenant, MeUser
from main_app.route.v1.deps import ActiveAppUserDep, OrganizationServiceDep
from modules.errors.openapi import problem_responses
from modules.tenancy.app_dependency import AppTenantContextDep

router = APIRouter()


@router.get("/me", summary="自分のプロフィール", responses=problem_responses())
def get_me(tenant: AppTenantContextDep, user: ActiveAppUserDep, organization_service: OrganizationServiceDep) -> MeRead:
    """ログイン中のテナントとユーザーを返す（`tenant_admin` / `member`）。

    `user.id` は AP のユーザー ID（ユーザー一覧の `id` と同じ）。`organizations` はユーザーが所属する有効な組織（組織名順。論理削除済みを除く）。
    テナントが停止中・削除要求中の場合は 403（`tenant_inactive`）。別のプレーン（CP）のセッション、
    無効化されたユーザー（`user_deactivated`）では 401。
    """
    organizations = organization_service.list_user_organizations(user.id)
    return MeRead(
        tenant=MeTenant(id=tenant.tenant_id, tenant_code=tenant.tenant_code),
        user=MeUser(id=user.id, username=user.claims.get("preferred_username"), email=user.claims.get("email"), roles=list(user.claims.get("roles") or [])),
        organizations=[MeOrganization(id=org.id, name=org.name) for org in organizations],
    )
