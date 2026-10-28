#!/usr/bin/env python
# coding:utf-8
"""``GET /api/v1/me``（自分のプロフィール。01 §10.2、§7.5）。

認証・テナント判定（AP セッション、ACTIVE なテナント）と CSRF 対策は ``main_app.route.v1.apiapp`` のルーターで適用済み。
テナントはコンテキスト（セッション → レジストリ照合）から、ユーザーはセッションから得る。リクエストの値は使わない。
AP のテーブルがまだ無いため DB には触れない。
"""
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from main_app.route.v1.api_me.schemas import MeRead, MeTenant, MeUser
from modules.auth.dependency import get_current_app_user
from modules.errors.openapi import problem_responses
from modules.tenancy.app_dependency import AppTenantContextDep

router = APIRouter()


@router.get("/me", summary="自分のプロフィール", responses=problem_responses())
def get_me(tenant: AppTenantContextDep, user: Annotated[dict[str, Any], Depends(get_current_app_user)]) -> MeRead:
    """ログイン中のテナントとユーザーを返す（`tenant_admin` / `member`）。

    テナントが停止中・削除要求中の場合は 403（`tenant_inactive`）。別のプレーン（CP）のセッションでは 401。
    """
    return MeRead(
        tenant=MeTenant(id=tenant.tenant_id, tenant_code=tenant.tenant_code),
        user=MeUser(id=user["sub"], username=user.get("preferred_username"), email=user.get("email"), roles=list(user.get("roles") or [])),
    )
