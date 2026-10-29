#!/usr/bin/env python
# coding:utf-8
"""アプリケーションプレーン（AP）のサービス層（FastAPI 非依存。02 §5.1）。

| モジュール | 内容 |
| --- | --- |
| :mod:`.user_sync` | ``sync_user_on_login``（ログイン時のユーザー同期・姓名とロールの写しの更新とデフォルト組織。PF-USR-04 / 05、PF-ORG-04）、``require_active_session_user``（各リクエストでの無効化ユーザーの拒否。PF-USR-03） |
| :mod:`.user_service` | ``UserService``（一覧（ID 指定可）・取得（IdP から写しを再同期）・作成・更新。PF-USR-01..03） |
| :mod:`.organization_service` | ``OrganizationService``（一覧・取得・ユーザーの所属組織・作成・更新・論理削除・メンバーの全置換。PF-ORG-01..03） |
| :mod:`.todo_service` | ``TodoService``（ToDo の一覧（総件数）・ホームの要約・取得・作成・更新・論理削除・担当者の全置換・アクティビティ。docs/spec/ToDoApp.md §9.3） |
| :mod:`.todo_comment_service` | ``TodoCommentService``（コメントの一覧・投稿・編集・論理削除。AP-CMT） |
| :mod:`.todo_checklist_service` | ``TodoChecklistService``（チェックリスト項目の参照・追加・更新・削除・並べ替え。AP-CHK） |
| :mod:`.todo_access` | ToDo の 3 つのサービスの共有部品（``actor_of`` / ``require_visible_todo``、記録、入力の補助） |
| :mod:`.todo_policy` | ToDo の閲覧範囲（SQL の条件）・表示範囲・操作の権限（コメントごとの権限を含む）。判定はここだけで行う（AP-VIS-09） |
| :mod:`.todo_views` | ToDo のビュー（``TodoView`` / ``TodoListPage`` / ``TodoDetailView`` / ``TodoActivityView`` / ``TodoActivityPage`` / ``TodoCommentView`` / ``TodoChecklistView`` / ``TodoSummaryView`` ほか） |
| :mod:`.errors` | 例外と Problem Details の ``code``・HTTP ステータスの対応 |
| :mod:`.common` | ビュー（``UserView`` / ``UserNameView`` / ``OrganizationView``）、``UNSET``、ロールの正規化、監査ログ・操作者の解決 |

いずれもテナントコンテキスト下の AP セッション（``AppSessionDep`` / ``open_app_session()``）で呼び、コミットはサービスが行う。
サブモジュールは個別に import する（本パッケージでは再エクスポートしない）。
"""
