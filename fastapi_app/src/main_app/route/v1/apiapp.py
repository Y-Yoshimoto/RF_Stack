#!/usr/bin/env python
# coding:utf-8
"""アプリケーションプレーン（AP）の API ルーター（``/api/v1``。01 §10.1）。

``app.py`` が ``prefix="/api/v1"``、``tags=["app"]`` を付け、``cp`` / ``public`` のルーターより**後に**マウントする。

ルーター全体に次を適用する。

- テナントコンテキスト（``AppTenantContextDep``）: AP のセッションを検証し（未認証は 401）、
  セッションのテナントをレジストリと照合する（停止中・削除要求中・不一致は 403）。CP のセッションでは 401。
- CSRF 対策（``require_csrf_protection``）: 状態を変える操作（POST / PUT / PATCH / DELETE）のみ。GET は素通り。

``/api/v1/cp`` と ``/api/v1/public`` は予約パスであり、AP のリソース名に使わない。
users / organizations（01 §8、§10.2）は AP のテーブルを作成した後に追加する。
"""
from fastapi import APIRouter, Depends

from main_app.route.v1.api_me.router import router as router_me
from modules.auth.csrf import require_csrf_protection
from modules.errors.openapi import problem_responses
from modules.tenancy.app_dependency import get_app_tenant_context

router = APIRouter(
    dependencies=[Depends(get_app_tenant_context), Depends(require_csrf_protection)],
    responses=problem_responses(401, 403),
)

router.include_router(router_me)
