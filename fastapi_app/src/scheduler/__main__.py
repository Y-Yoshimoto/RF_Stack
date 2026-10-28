#!/usr/bin/env python
# coding:utf-8
"""スケジューラだけを別プロセスで動かす（01 §14「定期実行の別プロセス / 別コンテナへの分離」用）。

fastapi_app コンテナ内（``src`` が ``PYTHONPATH``）で実行する::

    uv run python -m scheduler

``SCHEDULER_ENABLED`` に関係なく起動する（このプロセスを起動すること自体が有効化の意思表示のため）。
別プロセスで動かす場合は、API のプロセス側を ``SCHEDULER_ENABLED=false`` にする。Ctrl+C / SIGTERM で停止する。
"""
import logging
import signal
import sys
from types import FrameType

from modules.tenancy.providers import dispose_providers
from scheduler.runner import create_scheduler


def _raise_system_exit(signum: int, _frame: FrameType | None) -> None:
    """SIGTERM を ``SystemExit`` に変え、後始末（``finally``）を通して終了させる。"""
    raise SystemExit(128 + signum)


def main() -> int:
    """``BlockingScheduler`` を起動し、停止するまで戻らない。

    Returns:
        int: 終了コード。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    signal.signal(signal.SIGTERM, _raise_system_exit)
    scheduler = create_scheduler(blocking=True)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        dispose_providers()
    return 0


if __name__ == "__main__":
    sys.exit(main())
