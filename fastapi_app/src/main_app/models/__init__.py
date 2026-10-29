#!/usr/bin/env python
# coding:utf-8
""" アプリケーションプレーンのテーブルモデル

    Alembic(`alembic/app/env.py`)はこのパッケージを import して `app_plane_metadata` を参照する。
    **テーブルモデルのモジュールを追加したら、`_TABLE_MODULES` と `_EXPORTS` に追加すること。**
    import 漏れのモデルは MetaData に載らず、autogenerate が DROP TABLE を生成する原因になる。

    テーブルモデルのモジュールは遅延 import する(PEP 562 の `__getattr__`)。
    `modules.tenancy.models` が `main_app.models.base` を import するため、ここでテーブルモデル
    (`modules.tenancy.models` を import する)を即時 import すると循環 import になる。
    `app_plane_metadata` / `app_plane_registry` またはテーブルモデルを本パッケージから参照した時点で、
    `_TABLE_MODULES` のすべてを読み込む(MetaData には常に全テーブルが載った状態で渡る)。

    例: `from main_app.models import TUser, TTodo, app_plane_metadata`
"""
import importlib
from types import ModuleType
from typing import Any

from .base import AppPlaneBase

# テーブルモデルのモジュール(MetaData に載せるため、参照時にすべて読み込む)
_TABLE_MODULES: tuple[str, ...] = ("ap_common", "todo")

# 本パッケージから公開する名前 -> 定義しているモジュール
_EXPORTS: dict[str, str] = {
    # MetaData / registry(テーブルモデルを読み込んでから返す)
    "app_plane_metadata": "base",
    "app_plane_registry": "base",
    # AP 共通テーブル
    "TUser": "ap_common",
    "TOrganization": "ap_common",
    "TOrganizationMember": "ap_common",
    "TApAuditLog": "ap_common",
    # ToDo
    "TTodo": "todo",
    "TTodoOrganization": "todo",
    "TTodoAssignee": "todo",
    "TTodoActivity": "todo",
    "TTodoComment": "todo",
    "TTodoChecklistItem": "todo",
    "TodoStatus": "todo",
    "TodoPriority": "todo",
    "TodoVisibility": "todo",
    "TodoActivityAction": "todo",
    "TODO_COMMENT_BODY_MAX_LENGTH": "todo",
    "TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH": "todo",
    "TODO_CHECKLIST_ITEMS_MAX": "todo",
}

__all__ = ["AppPlaneBase", *_EXPORTS]


def load_table_modules() -> list[ModuleType]:
    """
        テーブルモデルのモジュールをすべて読み込む(MetaData にテーブルを登録する)
        return: 読み込んだモジュール
    """
    return [importlib.import_module(f"{__name__}.{name}") for name in _TABLE_MODULES]


def __getattr__(name: str) -> Any:
    """ 公開名を遅延解決する(テーブルモデルのモジュールをすべて読み込んでから返す) """
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    load_table_modules()
    value = getattr(importlib.import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """ 遅延解決する公開名も dir() に含める """
    return sorted(set(globals()) | set(_EXPORTS))
