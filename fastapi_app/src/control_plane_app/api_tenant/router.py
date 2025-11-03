#!/usr/bin/env python
# coding:utf-8
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, HTTPException

# モデルインポート
from control_plane_app.models.sql_models import * # noqa: F403, F401

# DB初期化
# DB接続用のモジュールをインポート
from modules.db_connector.engine import DBConnector
# DBコネクタ作成
control_plane_db_connector = DBConnector(
        dbuser=os.environ["APP_DB_USER"],
        dbpassword=os.environ["APP_DB_PASSWORD"],
        dbhost=os.environ["DB_HOST"],
        dbport=os.environ["DB_PORT"],
        dbname=os.environ["CONTROL_PLANE_DB_NAME"]
)
c_db = control_plane_db_connector
SessionDep = control_plane_db_connector.SessionDep
@asynccontextmanager
async def lifespan(app: FastAPI):
    # アプリ起動時処理, DBとテーブル作成
    # 最適な場所を検討する/一階層上のapiapp.py
    print("Creating control_plane DB and tables...")
    control_plane_db_connector.create_db_and_tables()
    yield
    pass


# APIルータ
router = APIRouter(lifespan=lifespan)

# エンドポイント
## ヘルスチェック
@router.get("/health", include_in_schema=False)
def read_root():
    # Rootパス動作確認
    # curl -L http://localhost:8000/control_plane/tenant/
    return {"Path": "/control_plane/tenant/health"}

# テナント一覧取得
## ToDo: SessionDepの型指定を修正
@router.get("/tenants", tags=["tenant"])
def get_tenants(session: SessionDep) -> list[T_Tenant]:
    """ テナント一覧取得 """
    tenants = session.exec(select(T_Tenant)).all()
    return tenants