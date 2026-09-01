#!/usr/bin/env python
# coding:utf-8
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# from proxy.apiapp import router as proxy
from control_plane_app.apiapp import router as router_control_plane
from main_app.route.auth.apiapp import router as router_auth
from main_app.route.sample.apiapp import router as router_sample
from modules.auth.environment import KeyCloakEnvironmentVariables

# サブモジュール読み込み
from rest_sample.apiapp import router as rest_sample_router

# アプリケーション起動
app = FastAPI()

# 秘密鍵が開発用の既定値のままでないことを起動時に検証する。
# APP_ENV=development では警告のみ、それ以外では RuntimeError で起動を止める。
KeyCloakEnvironmentVariables().validate_secrets()
# CORS 設定
# 通常運用ではブラウザからのアクセスは Vite の proxy 経由で同一オリジンになるため、
# CORS は不要であり既定では無効。ブラウザから FastAPI に直接アクセスする構成でのみ、
# 環境変数 CORS_ALLOW_ORIGINS にカンマ区切りでオリジンを設定して有効化する。
#   例: CORS_ALLOW_ORIGINS=http://localhost:5173
cors_allow_origins = [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if origin.strip()]
if cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
# サブモジュール読み込み
# 参考: https://fastapi.tiangolo.com/tutorial/bigger-applications/#import-fastapi
app.include_router(rest_sample_router)
app.include_router(router_auth, prefix="/api/auth", tags=["auth"])
app.include_router(router_sample, tags=["sample"])
# コントロールプレーン
app.include_router(
    router_control_plane,
    prefix="/control_plane",
    tags=["control_plane"],
)



@app.get("/", include_in_schema=False)
def read_root():
    return {"Path": "root"}

# 暫定/api/demo/loginエンドポイント(Keycloak実装とは別の簡易デモ用。本番の認証には使用しない)
@app.post("/api/demo/login", include_in_schema=False)
def demo_login(request: dict):
    print("Login request received: ", request)
    print(request.get("password"))
    if request.get("password") != "Pass":
        raise HTTPException(status_code=404, detail="Unauthorized")
    return {"message": "Login successful"}


def main():
    # サーバー起動
    uvicorn.run(app=app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
