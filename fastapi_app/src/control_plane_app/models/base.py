#!/usr/bin/env python
# coding:utf-8
""" コントロールプレーン用のモデルベース

    コントロールプレーン DB(`CONTROL_PLANE_DB_NAME`)のテーブルモデルは必ず `ControlPlaneBase` を継承する。
    `SQLModel` を直接継承すると、グローバルな `SQLModel.metadata` に登録され、
    Alembic(`alembic/control_plane/env.py`)の autogenerate 対象から外れる。

    例:
        class TTenant(ControlPlaneBase, table=True):
            __tablename__ = "t_tenant"
            ...
"""
from sqlalchemy import MetaData
from sqlmodel import SQLModel

from modules.db_connector.metadata import create_plane_registry

# コントロールプレーン専用の registry / MetaData
control_plane_registry = create_plane_registry()
control_plane_metadata: MetaData = control_plane_registry.metadata


class ControlPlaneBase(SQLModel, registry=control_plane_registry):
    """ コントロールプレーンのテーブルモデルの基底クラス(テーブルは持たない) """
