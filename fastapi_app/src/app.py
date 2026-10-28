#!/usr/bin/env python
# coding:utf-8
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# from proxy.apiapp import router as proxy
from control_plane_app.apiapp import router as router_control_plane
from control_plane_app.problems import register_cp_exception_handlers
from main_app.route.auth.apiapp import router as router_auth
from main_app.route.auth.dev_login import router as router_dev_login
from main_app.route.public.apiapp import router as router_public
from main_app.route.sample.apiapp import router as router_sample
from main_app.route.v1.apiapp import router as router_app
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.errors.handlers import register_exception_handlers
from modules.errors.openapi import install_problem_openapi
from modules.errors.request_id import RequestIdMiddleware
from modules.tenancy.providers import dispose_providers

# サブモジュール読み込み
from rest_sample.apiapp import router as rest_sample_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """アプリケーションの起動・終了処理。終了時に DB エンジン・レジストリを破棄する。"""
    yield
    dispose_providers()


# OpenAPI のタグ(03 §8)。エンドポイントの tags は app / cp / public / auth のいずれかを付ける。
OPENAPI_TAGS = [
    {"name": "app", "description": "アプリケーションプレーン(AP)。`/api/v1`。AP セッション(`rf_sid_app`)が必要"},
    {"name": "cp", "description": "コントロールプレーン(CP)。`/api/v1/cp`。CP セッション(`rf_sid_cp`)と `saas_admin` / `saas_viewer` が必要"},
    {"name": "public", "description": "認証なしの公開 API。`/api/v1/public`。ヘルスチェックとテナント存在確認"},
    {"name": "auth", "description": "ログイン・コールバック・ログアウト・認証状態(BFF)。`/api/auth`"},
]

# アプリケーション起動
app = FastAPI(
    title="RF Stack API",
    version="1.0.0",
    description="マルチテナント SaaS 共通基盤の API。エラーは RFC 9457 Problem Details(`application/problem+json`)。日時は UTC(`Z`)の ISO 8601。",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
# エラー応答を Problem Details に統一する(03 §2)
register_exception_handlers(app)
register_cp_exception_handlers(app)
install_problem_openapi(app)

# 秘密鍵が開発用の既定値のままでないことを起動時に検証する。
# APP_ENV=development では警告のみ、それ以外では RuntimeError で起動を止める。
_auth_config = KeyCloakEnvironmentVariables()
_auth_config.validate_secrets()
# 開発用ログインバイパスが本番で有効化されていないことを検証する。
_auth_config.validate_dev_login()
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
# リクエスト ID(X-Request-ID)の受け取り・生成。最後に追加したものが最も外側になる
app.add_middleware(RequestIdMiddleware)
# サブモジュール読み込み
# 参考: https://fastapi.tiangolo.com/tutorial/bigger-applications/#import-fastapi
app.include_router(rest_sample_router)
app.include_router(router_auth, prefix="/api/auth", tags=["auth"])
# 開発用ログインバイパス。有効時のみ登録し、無効時はルート自体が存在しない(404)。
if _auth_config.is_dev_login_enabled():
    app.include_router(router_dev_login, prefix="/api/auth", tags=["auth"])
app.include_router(router_sample, tags=["sample"])
# /api/v1 配下。cp / public は予約パスであり、AP のルーターより先に登録する(01 §10.1)
app.include_router(router_control_plane, prefix="/api/v1/cp", tags=["cp"])
app.include_router(router_public, prefix="/api/v1/public", tags=["public"])
app.include_router(router_app, prefix="/api/v1", tags=["app"])


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
