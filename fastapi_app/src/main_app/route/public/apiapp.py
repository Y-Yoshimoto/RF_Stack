#!/usr/bin/env python
# coding:utf-8
"""公開 API のルーター（``/api/v1/public``。01 §10.1）。認証なし。

``app.py`` が ``prefix="/api/v1/public"``、``tags=["public"]`` を付けてマウントする。
ヘルスチェックとテナント存在確認（ログイン前に使う）を提供する。
"""
from fastapi import APIRouter

from main_app.route.public.api_health.router import router as router_health
from main_app.route.public.api_tenant_lookup.router import router as router_tenant_lookup

router = APIRouter()

router.include_router(router_health, prefix="/health")
router.include_router(router_tenant_lookup, prefix="/tenants")
