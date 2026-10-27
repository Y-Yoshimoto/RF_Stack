#!/usr/bin/env python
# coding:utf-8
""" アプリケーションプレーン用のモデルベース

    アプリケーションプレーン DB(`APP_DB_NAME`)のテーブルモデルは必ず `AppPlaneBase` を継承する。
    テナントスコープのテーブルは `modules.tenancy.models.TenantScopedBase`(本クラスの派生)を使う。
    `SQLModel` を直接継承すると、グローバルな `SQLModel.metadata` に登録され、
    Alembic(`alembic/app/env.py`)の autogenerate 対象から外れる。
"""
from sqlalchemy import MetaData
from sqlmodel import SQLModel

from modules.db_connector.metadata import create_plane_registry

# アプリケーションプレーン専用の registry / MetaData
app_plane_registry = create_plane_registry()
app_plane_metadata: MetaData = app_plane_registry.metadata


class AppPlaneBase(SQLModel, registry=app_plane_registry):
    """ アプリケーションプレーンのテーブルモデルの基底クラス(テーブルは持たない) """
