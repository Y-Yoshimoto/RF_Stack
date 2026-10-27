#!/usr/bin/env python
# coding:utf-8
# モデル読み込み
# ログ設定
import logging

from fastapi import APIRouter, Depends, HTTPException

from modules.auth import get_current_user

from .model import SampleData

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s %(name)s %(filename)s:%(lineno)d %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# APIルータ
router = APIRouter()

# 各エンドポイントの ``_current_user`` は認証を強制するための依存であり、
# ハンドラ内では使用しない。使用する例は main_app/route/sample/apiapp.py を参照。


@router.get("/RestSample/", include_in_schema=False)
def read_root(_current_user: dict = Depends(get_current_user)):
    # Rootパス用
    return {"Path": "/RestSample/"}


@router.get("/RestSample/{id}")
def sample_get(id: int, _current_user: dict = Depends(get_current_user)):
    """
    Getメソッドのサンプル

    Args:
        id (int): アイテムのID

    Returns:
        data (SampleData): IDと情報を含む辞書
    """
    return SampleData(**{'id': id})


@router.post("/RestSample/")
def sample_post(data: SampleData, _current_user: dict = Depends(get_current_user)):
    """
    Postメソッドのサンプル
    bodyで受け取ったnameで、デフォルト値を上書きして返す

    Args:
        data (SampleData): 更新データ

    Returns:
        dict: IDと情報を含む辞書

    """
    return data


@router.put("/RestSample/{id}")
def sample_put(data: SampleData, _current_user: dict = Depends(get_current_user)):
    """
    Putメソッドのサンプル
    bodyで受け取ったnameで、デフォルト値を上書きして返す

    Args:
        id (int): 更新対象のID
        data (SampleData): 更新データ

    Returns:
        dict: IDと情報を含む辞書

    """
    print(data)
    if (data.id is None):
        raise HTTPException(status_code=400, detail="id does not match")
    return data


@router.delete("/RestSample/{id}")
def sample_delete(id: int, _current_user: dict = Depends(get_current_user)):
    """
    Deleteメソッドのサンプル

    Args:
        id (int): 削除対象のID

    Returns:
        dict: IDを含む辞書

    """
    return {"id": id}
