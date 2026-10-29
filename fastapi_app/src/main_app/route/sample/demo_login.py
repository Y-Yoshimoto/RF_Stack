#!/usr/bin/env python
# coding:utf-8
"""簡易デモ用ログイン(`/api/demo/login`)のサンプル実装。

アプリに登録していない参考用のコード。`app.py` から `include_router` していないため、このルートは公開されない(import もされない)。
Keycloak による認証(`main_app/route/auth`)とは別の簡易デモ用で、本番の認証には使用しない。
`app.py` に直書きされていたものを、削除せずここへ移した。
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/api/demo/login", include_in_schema=False)
def demo_login(request: dict):
    print("Login request received: ", request)
    print(request.get("password"))
    if request.get("password") != "Pass":
        raise HTTPException(status_code=404, detail="Unauthorized")
    return {"message": "Login successful"}
