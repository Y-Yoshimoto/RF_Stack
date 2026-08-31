#!/usr/bin/env python
# coding:utf-8
"""認証で保護された TODO API のサンプル実装。"""
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
def list_todos(_: dict = Depends(get_current_user)):
	"""認証済みユーザー向けの TODO 一覧取得サンプル。"""
	return {
		"todos": [
			{"id": 1, "title": "Write API sample", "completed": False},
			{"id": 2, "title": "Check auth dependency", "completed": True},
		]
	}


@router.post("/sample/todos")
def create_todo(_: TodoCreateRequest, __: dict = Depends(get_current_user)):
	"""認証済みユーザー向けの TODO 作成サンプル。"""
	return {"status": "success"}


@router.put("/sample/todos/{todo_id}")
def update_todo(todo_id: int, _: TodoUpdateRequest, __: dict = Depends(get_current_user)):
	"""認証済みユーザー向けの TODO 更新サンプル。"""
	_ = todo_id
	return {"status": "success"}


@router.delete("/sample/todos/{todo_id}")
def delete_todo(todo_id: int, _: dict = Depends(get_current_user)):
	"""認証済みユーザー向けの TODO 削除サンプル。"""
	_ = todo_id
	return {"status": "success"}
