"""定期ジョブのスケジューラ（01 §12.1、02 §5.5）。スケジュール定義と起動処理はこのパッケージに閉じ込める。

- :mod:`scheduler.schedule` — ジョブと周期の定義（:data:`~scheduler.schedule.SCHEDULED_JOBS`）
- :mod:`scheduler.runner` — APScheduler の生成・起動・停止、有効/無効の判定、FastAPI の lifespan 用コンテキスト
- ``python -m scheduler`` — スケジューラだけを別プロセスで動かす（将来の別コンテナ化用）

ジョブ本体は ``control_plane_app/jobs/`` の普通の関数で、二重実行は本体側の advisory lock で防ぐ。
"""
