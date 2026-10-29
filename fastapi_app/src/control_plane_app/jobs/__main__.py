#!/usr/bin/env python
# coding:utf-8
"""定期ジョブを CLI から 1 回実行する（01 §12.1「CLI からも実行できる」）。

fastapi_app コンテナ内（``src`` が ``PYTHONPATH``）で実行する::

    uv run python -m control_plane_app.jobs provisioning_reaper
    uv run python -m control_plane_app.jobs tenant_purge
    uv run python -m control_plane_app.jobs metrics_snapshot

結果（ステータス・対象テナント ID）を JSON で標準出力に表示する。

終了コード:
    0: SUCCEEDED / SKIPPED、1: FAILED
"""
import argparse
import json
import logging
import sys
from collections.abc import Callable

from control_plane_app.jobs.metrics_snapshot import JOB_NAME as METRICS_SNAPSHOT
from control_plane_app.jobs.metrics_snapshot import run_metrics_snapshot
from control_plane_app.jobs.provisioning_reaper import JOB_NAME as PROVISIONING_REAPER
from control_plane_app.jobs.provisioning_reaper import run_provisioning_reaper
from control_plane_app.jobs.runner import JobRunResult
from control_plane_app.jobs.tenant_purge import JOB_NAME as TENANT_PURGE
from control_plane_app.jobs.tenant_purge import run_tenant_purge
from control_plane_app.models.sql_models import RunStatus

# ジョブ名 -> 本体（引数なしで既定の接続・設定を使う）
JOBS: dict[str, Callable[[], JobRunResult]] = {
    PROVISIONING_REAPER: run_provisioning_reaper,
    TENANT_PURGE: run_tenant_purge,
    METRICS_SNAPSHOT: run_metrics_snapshot,
}


def main(argv: list[str] | None = None) -> int:
    """CLI のエントリポイント。

    Args:
        argv: コマンドライン引数（``None`` なら ``sys.argv[1:]``）。

    Returns:
        int: 終了コード。
    """
    parser = argparse.ArgumentParser(prog="python -m control_plane_app.jobs", description="コントロールプレーンの定期ジョブを 1 回実行する。")
    parser.add_argument("job_name", choices=list(JOBS))
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ (INFO) を標準エラーに出力する")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    result = JOBS[args.job_name]()
    print(json.dumps({"job_name": result.job_name, "status": result.status.value, "run_id": str(result.run_id), "detail": result.detail, "error": result.error}, ensure_ascii=False))
    return 1 if result.status == RunStatus.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
