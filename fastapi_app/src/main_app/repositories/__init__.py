#!/usr/bin/env python
# coding:utf-8
"""アプリケーションプレーン（AP）の DB アクセス（``app_db``。RLS 適用のセッションで使う）。

- :mod:`.users` — ``t_user``
- :mod:`.organizations` — ``t_organization`` / ``t_organization_member``（既定で論理削除済みを除く）
- :mod:`.audit_log` — ``t_ap_audit_log`` の追記
- :mod:`.keyset` — 一覧のキーセット方式（カーソル）の部品
- :mod:`.todos` — ToDo（docs/spec/ToDoApp.md §9.2）

コミットはしない（トランザクションの境界は呼び出し側のサービス層が決める）。
"""
