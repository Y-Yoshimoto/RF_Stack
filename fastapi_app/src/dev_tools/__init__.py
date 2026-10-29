#!/usr/bin/env python
# coding:utf-8
"""開発専用の補助処理（02 §5.1）。本番では使わない。

- :mod:`dev_tools.e2e_cleanup` — Playwright の E2E が作る使い捨てデータの後片付け（``python -m dev_tools.e2e_cleanup [--dry-run]``）

いずれも ``APP_ENV=development`` かつ開発用ログインが有効（``AUTH_DEV_LOGIN_ENABLED``）な場合だけ動き、それ以外では例外を出して何もしない。
サブモジュールは個別に import する（本パッケージでは再エクスポートしない。``python -m`` で二重に読み込まれないようにするため）。
"""
