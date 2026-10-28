"""ToDo の DB アクセス（docs/spec/ToDoApp.md §9.2）。

- :mod:`.todos` — ``t_todo`` / ``t_todo_assignee`` / ``t_todo_organization``（閲覧範囲の条件は ``main_app.services.todo_policy`` から受け取る）
- :mod:`.activities` — ``t_todo_activity`` の追記と一覧
- :mod:`.metrics` — テーマ固有メトリクス（CP の日次スナップショットから呼ばれる）
"""
