#!/usr/bin/env python
# coding:utf-8
"""認証で保護された TODO API のサンプル実装。

アプリに登録していない参考用のコード。`app.py` から `include_router` していないため、このルートは公開されない(import もされない)。

``Depends(get_current_user)`` を付けるだけでエンドポイントを保護できることと、
取得した認証済みユーザー情報をハンドラ内で利用する方法を示すためのサンプル。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from modules.auth import get_current_user

router = APIRouter()


class TodoCreateRequest(BaseModel):
    """TODO 作成リクエスト。"""

    title: str = Field(..., description="TODO タイトル")
    completed: bool = Field(default=False, description="完了フラグ")


class TodoUpdateRequest(BaseModel):
    """TODO 更新リクエスト。"""

    title: str = Field(..., description="TODO タイトル")
    completed: bool = Field(..., description="完了フラグ")


@router.get("/sample/todos")
def list_todos(current_user: dict = Depends(get_current_user)):
    """認証済みユーザー向けの TODO 一覧取得サンプル。

    実際のアプリケーションでは ``current_user`` の ``sub`` や ``realm`` を条件に
    データを絞り込む。ここでは応答に含めることで、認証情報がハンドラまで
    渡っていることを確認できるようにしている。

    Args:
        current_user: 認証済みユーザー情報。

    Returns:
        dict: TODO 一覧と、取得したユーザーの識別情報。
    """
    return {
        "owner": {
            "sub": current_user.get("sub"),
            "preferred_username": current_user.get("preferred_username"),
            "realm": current_user.get("realm"),
        },
        "todos": [
            {"id": 1, "title": "Write API sample", "completed": False},
            {"id": 2, "title": "Check auth dependency", "completed": True},
        ],
    }


@router.post("/sample/todos")
def create_todo(request: TodoCreateRequest, current_user: dict = Depends(get_current_user)):
    """認証済みユーザー向けの TODO 作成サンプル。

    Args:
        request: 作成する TODO の内容。
        current_user: 認証済みユーザー情報。作成者の記録に使用する想定。

    Returns:
        dict: 作成結果と、作成された TODO の内容。
    """
    return {
        "status": "success",
        "todo": {
            "title": request.title,
            "completed": request.completed,
            "created_by": current_user.get("sub"),
        },
    }


@router.put("/sample/todos/{todo_id}")
def update_todo(todo_id: int, request: TodoUpdateRequest, current_user: dict = Depends(get_current_user)):
    """認証済みユーザー向けの TODO 更新サンプル。

    Args:
        todo_id: 更新対象の TODO ID。
        request: 更新後の内容。
        current_user: 認証済みユーザー情報。所有者確認に使用する想定。

    Returns:
        dict: 更新結果と、更新後の TODO の内容。
    """
    return {
        "status": "success",
        "todo": {
            "id": todo_id,
            "title": request.title,
            "completed": request.completed,
            "updated_by": current_user.get("sub"),
        },
    }


@router.delete("/sample/todos/{todo_id}")
def delete_todo(todo_id: int, current_user: dict = Depends(get_current_user)):
    """認証済みユーザー向けの TODO 削除サンプル。

    Args:
        todo_id: 削除対象の TODO ID。
        current_user: 認証済みユーザー情報。所有者確認に使用する想定。

    Returns:
        dict: 削除結果と、削除した TODO の ID。
    """
    return {
        "status": "success",
        "id": todo_id,
        "deleted_by": current_user.get("sub"),
    }
