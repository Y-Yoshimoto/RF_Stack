"""コントロールプレーンの定期ジョブ本体（スケジューラに依存しない普通の関数。01 §12.1、02 §5.5）。

| ジョブ | 関数 | 内容 |
| --- | --- | --- |
| ``provisioning_reaper`` | :func:`control_plane_app.jobs.provisioning_reaper.run_provisioning_reaper` | 長時間 ``PROVISIONING`` の払い出しを ``FAILED`` にする（CP-ONB-09） |
| ``tenant_purge`` | :func:`control_plane_app.jobs.tenant_purge.run_tenant_purge` | 猶予期間を過ぎたテナントを物理削除する（CP-OPS-08） |
| ``metrics_snapshot`` | :func:`control_plane_app.jobs.metrics_snapshot.run_metrics_snapshot` | テナント毎のメトリクスを日次メトリクスに UPSERT する（CP-MET-05） |

各関数は ``pg_try_advisory_lock(hashtext('<job_name>'))`` で二重実行を防ぎ、``t_scheduled_job_run`` に実行結果を記録する
（:mod:`control_plane_app.jobs.runner`）。CLI からも実行できる::

    uv run python -m control_plane_app.jobs provisioning_reaper
    uv run python -m control_plane_app.jobs tenant_purge
    uv run python -m control_plane_app.jobs metrics_snapshot

周期の定義と起動はスケジューラ（``scheduler/``）に閉じ込めている（本パッケージはスケジューラに依存しない）。
"""
