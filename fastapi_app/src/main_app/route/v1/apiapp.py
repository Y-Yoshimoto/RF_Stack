#!/usr/bin/env python
# coding:utf-8
"""アプリケーションプレーン（AP）の API ルーター（``/api/v1``。01 §10.1）。

``app.py`` が ``prefix="/api/v1"``、``tags=["app"]`` を付け、``cp`` / ``public`` のルーターより**後に**マウントする。

ルーター全体に次を、この順に適用する（依存関数の宣言順に評価される）。

1. テナントコンテキスト（``get_app_tenant_context``）: AP のセッションを検証し（未認証は 401）、
   セッションのテナントをレジストリと照合する（停止中・削除要求中・不一致は 403）。CP のセッションでは 401。
2. CSRF 対策（``require_csrf_protection``）: 状態を変える操作（POST / PUT / PATCH / DELETE）のみ。GET は素通り。
3. セッションのユーザーが AP で有効か（``require_active_app_user``。01 PF-USR-03、05 #32）: 無効化されたユーザー・
   AP のユーザー行が無いユーザーは、Redis のセッションを破棄して 401（``user_deactivated`` / ``user_not_synced``）。

各エンドポイントのロール確認（``tenant_admin`` / ``member``）は、これらの後に評価される。

``/api/v1/cp`` と ``/api/v1/public`` は予約パスであり、AP のリソース名に使わない。
"""
from fastapi import APIRouter, Depends

from main_app.route.v1.api_me.router import router as router_me
from main_app.route.v1.api_organizations.router import router as router_organizations
from main_app.route.v1.api_users.router import router as router_users
from main_app.route.v1.deps import require_active_app_user
from modules.auth.csrf import require_csrf_protection
from modules.errors.openapi import problem_responses
from modules.tenancy.app_dependency import get_app_tenant_context

router = APIRouter(
    dependencies=[Depends(get_app_tenant_context), Depends(require_csrf_protection), Depends(require_active_app_user)],
    responses=problem_responses(401, 403),
)

router.include_router(router_me)
router.include_router(router_users, prefix="/users")
router.include_router(router_organizations, prefix="/organizations")
