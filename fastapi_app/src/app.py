#!/usr/bin/env python
# coding:utf-8
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# サブモジュール読み込み
from rest_sample.apiapp import router as RestSample
# from proxy.apiapp import router as proxy
from control_plane_app.apiapp import router as router_control_plane
from main_app.route.auth.apiapp import router as router_auth
from main_app.route.sample.apiapp import router as router_sample

# アプリケーション起動
app = FastAPI()
# 開発環境のフロントエンドとの接続を許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# サブモジュール読み込み
# 参考: https://fastapi.tiangolo.com/tutorial/bigger-applications/#import-fastapi
app.include_router(RestSample)
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

def main():
    # サーバー起動
    uvicorn.run(app=app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
