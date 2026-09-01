#!/usr/bin/env python
# coding:utf-8
"""rest_sample ルータの結合テスト。

これらのエンドポイントは ``Depends(get_current_user)`` で保護されているため、
未認証では 401 になる。認証済みの挙動は ``dependency_overrides`` で
Dependency を差し替えて検証する。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth import get_current_user
from rest_sample.apiapp import router as rest_sample_router

app = FastAPI()
app.include_router(rest_sample_router)
client = TestClient(app)


def _override_current_user() -> dict:
    """認証済みユーザーを模したデータを返す。"""
    return {
        "sub": "sample-user",
        "preferred_username": "sample",
        "email": "sample@example.com",
        "realm": "sample",
    }


def test_read_main_requires_auth():
    """未認証でアクセスすると 401 を返すこと。"""
    response = client.get("/RestSample/")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_read_main_with_auth():
    """認証済みならルートパスの応答を返すこと。"""
    app.dependency_overrides[get_current_user] = _override_current_user
    try:
        response = client.get("/RestSample/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"Path": "/RestSample/"}


def test_sample_get_with_auth():
    """認証済みなら ID を指定して取得できること。"""
    app.dependency_overrides[get_current_user] = _override_current_user
    try:
        response = client.get("/RestSample/123")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["id"] == 123
