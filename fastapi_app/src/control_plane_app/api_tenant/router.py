#!/usr/bin/env python
# coding:utf-8
import os

from fastapi import APIRouter
from sqlmodel import select

# モデルインポート
from control_plane_app.models.sql_models import TTenant

# DB接続用のモジュールをインポート
from modules.db_connector.engine import DBConnector

# DBコネクタ作成
# 実行時はマイグレーション用の所有者ロール(CP_DB_OWNER_*)ではなく、DML 権限のみのランタイムロールで接続する。
# テーブルの作成・変更は Alembic(alembic/alembic_control_plane.ini)で行い、アプリ起動時には行わない。
control_plane_db_connector = DBConnector(
        dbuser=os.environ["CP_DB_RUNTIME_USER"],
        dbpassword=os.environ["CP_DB_RUNTIME_PASSWORD"],
        dbhost=os.environ["DB_HOST"],
        dbport=os.environ["DB_PORT"],
        dbname=os.environ["CONTROL_PLANE_DB_NAME"]
)
c_db = control_plane_db_connector
SessionDep = control_plane_db_connector.SessionDep


# APIルータ
router = APIRouter()

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
def get_tenants(session: SessionDep) -> list[TTenant]:
    """ テナント一覧取得 """
    tenants = session.exec(select(TTenant)).all()
    return tenants
