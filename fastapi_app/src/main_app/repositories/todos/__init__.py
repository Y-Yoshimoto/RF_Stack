"""ToDo の DB アクセス（docs/spec/ToDoApp.md §9.2）。

- :mod:`.todos` — ``t_todo`` / ``t_todo_assignee`` / ``t_todo_organization``（閲覧範囲の条件は ``main_app.services.todo_policy`` から受け取る）、
  一覧の総件数 ``count_todos``・件数 ``load_todo_counters``（進捗・コメント数）・ホームの要約 ``summary_counts``
- :mod:`.activities` — ``t_todo_activity`` の追記と一覧
- :mod:`.comments` — ``t_todo_comment``（コメント。古い順の一覧は投稿者を結合して 1 クエリ）
- :mod:`.checklist` — ``t_todo_checklist_item``（チェックリスト項目）と ``t_todo.checklist_version``
- :mod:`.metrics` — テーマ固有メトリクス（CP の日次スナップショットから呼ばれる）
"""
