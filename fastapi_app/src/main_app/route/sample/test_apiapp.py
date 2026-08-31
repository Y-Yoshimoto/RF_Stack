#!/usr/bin/env python
# coding:utf-8
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main_app.route.sample.apiapp import router as sample_router
from modules.auth import get_current_user


app = FastAPI()
app.include_router(sample_router)
client = TestClient(app)


def _override_current_user() -> dict:
    return {
        "sub": "sample-user",
        "preferred_username": "sample",
        "email": "sample@example.com",
        "realm": "sample",
    }


def test_sample_todos_requires_auth():
    """未認証アクセス時に 401 を返すこと。"""
    response = client.get("/sample/todos")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_sample_todos_get_with_auth_override():
    """認証済みとして TODO 一覧を取得できること。"""
    app.dependency_overrides[get_current_user] = _override_current_user
    response = client.get("/sample/todos")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert "todos" in body
    assert isinstance(body["todos"], list)


def test_sample_todos_post_put_delete_with_auth_override():
    """認証済みとして CRUD の更新系が success を返すこと。"""
    app.dependency_overrides[get_current_user] = _override_current_user

    post_response = client.post(
        "/sample/todos",
        json={"title": "New TODO", "completed": False},
    )
    put_response = client.put(
        "/sample/todos/1",
        json={"title": "Updated TODO", "completed": True},
    )
    delete_response = client.delete("/sample/todos/1")

    app.dependency_overrides.clear()

    assert post_response.status_code == 200
    assert post_response.json() == {"status": "success"}

    assert put_response.status_code == 200
    assert put_response.json() == {"status": "success"}

    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "success"}