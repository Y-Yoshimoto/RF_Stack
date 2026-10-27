#!/usr/bin/env python
# coding:utf-8
""" プレーン毎の MetaData / registry 生成

    SQLModel は既定で全テーブルモデルをグローバルな `SQLModel.metadata` に登録する。
    コントロールプレーンとアプリケーションプレーンは別 DB のため、両プレーンのモデルを同一プロセスで
    import すると、Alembic の autogenerate が他プレーンのテーブルを作成・削除しようとする。

    これを避けるため、プレーン毎に独立した SQLAlchemy の `registry`(= 独立した MetaData)を作り、
    プレーン毎のベースクラスを `class XxxBase(SQLModel, registry=xxx_registry)` で定義する。
    テーブルモデルはそのベースクラスを継承することで、各プレーンの MetaData にのみ登録される。

    - コントロールプレーン: `control_plane_app.models.base.ControlPlaneBase`
    - アプリケーションプレーン: `main_app.models.base.AppPlaneBase`
"""
from sqlalchemy import MetaData
from sqlalchemy.orm import registry

# 制約・インデックスの命名規約
# PostgreSQL が自動で付ける名前と同じ形式にそろえ、Alembic で制約を確実に参照できるようにする。
# (ix は SQLAlchemy の既定値と同じ)
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


def create_plane_registry() -> registry:
    """
        プレーン専用の registry を生成する
        return: 独立した MetaData を持つ registry
    """
    return registry(metadata=MetaData(naming_convention=NAMING_CONVENTION))
