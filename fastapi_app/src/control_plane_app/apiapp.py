#!/usr/bin/env python
# coding:utf-8
# モデル読み込み
from fastapi import APIRouter, HTTPException

from .api_tenant.router import router as router_tenant

# APIルータ
router = APIRouter()

# テナント管理
router.include_router(
    router_tenant,
    prefix="/tenant",
    tags=["tenant"],
)


@router.get("/", include_in_schema=False)
def read_root():
    # Rootパス動作確認
    # curl -L http://localhost:8000/control_plane/
    return {"Path": "/control_plane/"}

