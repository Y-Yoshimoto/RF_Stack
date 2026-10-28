#!/usr/bin/env python
# coding:utf-8
"""アプリケーションプレーン（AP）のサービス層（FastAPI 非依存。02 §5.1）。

| モジュール | 内容 |
| --- | --- |
| :mod:`.user_sync` | ``sync_user_on_login``（ログイン時のユーザー同期とデフォルト組織。PF-USR-04 / 05、PF-ORG-04）、``require_active_session_user``（各リクエストでの無効化ユーザーの拒否。PF-USR-03） |
| :mod:`.user_service` | ``UserService``（一覧・取得・作成・更新。PF-USR-01..03） |
| :mod:`.organization_service` | ``OrganizationService``（一覧・取得・作成・更新・論理削除・メンバーの全置換。PF-ORG-01..03） |
| :mod:`.errors` | 例外と Problem Details の ``code``・HTTP ステータスの対応 |
| :mod:`.common` | ビュー（``UserView`` / ``OrganizationView``）、``UNSET``、監査ログ・操作者の解決 |

いずれもテナントコンテキスト下の AP セッション（``AppSessionDep`` / ``open_app_session()``）で呼び、コミットはサービスが行う。
サブモジュールは個別に import する（本パッケージでは再エクスポートしない）。
"""
