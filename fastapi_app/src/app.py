#!/usr/bin/env python
# coding:utf-8
import uvicorn
from fastapi import FastAPI, HTTPException

# サブモジュール読み込み
from rest_sample.apiapp import router as RestSample
# from proxy.apiapp import router as proxy
from control_plane_app.apiapp import router as router_control_plane

# アプリケーション起動
app = FastAPI()
# サブモジュール読み込み
# 参考: https://fastapi.tiangolo.com/tutorial/bigger-applications/#import-fastapi
app.include_router(RestSample)
# コントロールプレーン
app.include_router(
    router_control_plane,
    prefix="/control_plane",
    tags=["control_plane"],
)



@app.get("/", include_in_schema=False)
def read_root():
    return {"Path": "root"}

# 暫定/api/loginエンドポイント
@app.post("/api/login", include_in_schema=False)
def login(request: dict):
    print("Login request received: ", request)
    print(request.get("password"))
    if request.get("password") != "password":
        raise HTTPException(status_code=404, detail="Unauthorized")
    return {"message": "Login successful"}

def main():
    # サーバー起動
    uvicorn.run(app=app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
