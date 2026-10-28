#!/usr/bin/env python
# coding:utf-8
"""コントロールプレーン（CP）の API ルーター（``/api/v1/cp``。01 §10.1、§10.2）。

``app.py`` が ``prefix="/api/v1/cp"``、``tags=["cp"]`` を付けてマウントする。

認可（01 §7.4、§7.5）:
    - ルーター全体に ``saas_admin`` または ``saas_viewer`` を要求する（未認証は 401、ロール不足は 403）。
      AP のセッション（``rf_sid_app``）では認証されない。
    - 状態を変える操作には CSRF 対策（``X-Requested-With`` と ``Origin``）を適用する。参照系（GET）は素通りする。
    - 変更系のエンドポイントは、さらに ``saas_admin`` を要求する（``saas_viewer`` は 403）。
"""
from fastapi import APIRouter, Depends

from control_plane_app.api_metrics.router import router as router_metrics
from control_plane_app.api_tenants.router import router as router_tenants
from modules.auth.csrf import require_csrf_protection
from modules.auth.dependency import require_cp_roles
from modules.errors.openapi import problem_responses

# 認可は依存関数の宣言順に評価される（認証・ロール → CSRF）。未認証の変更系リクエストは CSRF の前に 401 になる。
router = APIRouter(
    dependencies=[Depends(require_cp_roles("saas_admin", "saas_viewer")), Depends(require_csrf_protection)],
    responses=problem_responses(401, 403),
)

router.include_router(router_tenants, prefix="/tenants")
router.include_router(router_metrics)
