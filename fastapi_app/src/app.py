#!/usr/bin/env python
# coding:utf-8
import uvicorn
from fastapi import FastAPI

# サブモジュール読み込み
from rest_sample.apiapp import router as RestSample
# from proxy.apiapp import router as proxy
from control_plane.apiapp import router as control_plane

# アプリケーション起動
app = FastAPI()
# サブモジュール読み込み
# 参考: https://fastapi.tiangolo.com/tutorial/bigger-applications/#import-fastapi
app.include_router(RestSample)
# コントロールプレーン
app.include_router(
    control_plane,
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
