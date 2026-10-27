#!/usr/bin/env python
# coding:utf-8
""" アプリケーションプレーンのテーブルモデル

    Alembic(`alembic/app/env.py`)はこのパッケージを import して `app_plane_metadata` を参照する。
    **テーブルモデルのモジュールを追加したら、ここで import すること。**
    import 漏れのモデルは MetaData に載らず、autogenerate が DROP TABLE を生成する原因になる。
"""
from .base import AppPlaneBase, app_plane_metadata, app_plane_registry

# テーブルモデルのモジュールはここに追加する
# from . import sql_models  # noqa: F401

__all__ = ["AppPlaneBase", "app_plane_metadata", "app_plane_registry"]
