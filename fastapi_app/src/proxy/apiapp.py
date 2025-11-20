#!/usr/bin/env python
# coding:utf-8
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Request
import httpx
router = APIRouter()
TARGET_API_BASE_URL = "https://api.open-meteo.com/v1/"

@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def reverse_proxy(path: str, request: Request):
    # クエリパラメータを取得してURLに追加


    # HTTPリクエストを別のサーバに転送
    async with httpx.AsyncClient() as client:
        request_args = await reRequest(path, request)
        print(f"Request Args: {request_args}")
        response = await client.request(**request_args)

    # 特定のパスに対するレスポンスのボディを書き換え
    if path.startswith("archive") and response.status_code == 200:
        print(f"Response: {response.content}")
        if response.headers.get("Content-Type") == "application/json; charset=utf-8":
            # print(f"Rewrite: {response.url} -----------------------------")
            original_body = response.json()
            # ボディの一部を書き換える例
            # print(f"Original Body: {original_body}")
            original_body["modified_key"] = "modified_value"
            # print(f"Modified Body: {original_body}")
            return JSONResponse(content=original_body, status_code=response.status_code, headers=response.headers)

    # レスポンスをそのまま返却
    return response
    # return JSONResponse(
    #     content=response.content.decode("utf-8"),
    #     status_code=response.status_code,
    #     headers=response.headers
    # )
    

### ヘルパー関数　
# クエリパラメータをURLに追加する関数
def addQuery_string(query_string: str) -> str:
    return f"?{query_string}" if query_string else ""

# 再リクエストパラメータに置き換える
async def reRequest (path: str, request: Request) -> object:
    request_args = {
            "method": request.method,
            "url": f"{TARGET_API_BASE_URL}/{path}{addQuery_string(request.url.query)}",
            "headers": dict(request.headers),
            "content": await request.body()
        }
    return request_args