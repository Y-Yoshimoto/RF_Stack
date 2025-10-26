#!/usr/bin/env python
# coding:utf-8
# モデル読み込み
from fastapi import APIRouter, HTTPException

# APIルータ
router = APIRouter()


@router.get("/", include_in_schema=False)
def read_root():
    # Rootパス動作確認
    # curl -L http://localhost:8000/control_plane/tenant/
    return {"Path": "/control_plane/tenant/"}

