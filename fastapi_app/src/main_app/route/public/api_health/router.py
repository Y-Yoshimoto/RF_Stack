#!/usr/bin/env python
# coding:utf-8
"""ヘルスチェック（``/api/v1/public/health``。01 §10.2）。認証なし。

- ``live``: プロセスが応答できるか。依存先は確認しない（失敗時の再起動判断に使う）。
- ``ready``: リクエストを処理できるか。次の 3 つに接続できることを確認する（失敗時はトラフィックから外す判断に使う）。

  | 確認先 | 理由 |
  | --- | --- |
  | CP DB（``cp_runtime``） | CP API・テナントレジストリ（AP の全リクエスト）に必要 |
  | AP DB（``app_runtime``） | AP API に必要 |
  | Redis | 全ての認証済みリクエスト（セッション）に必要 |

  **Keycloak は確認しない。** Keycloak が停止してもログイン済みのセッションは使い続けられ、
  影響はログイン・払い出し・トークン更新に限られる。ここに含めると Keycloak の障害で全 API がトラフィックから外れ、
  かえって影響が広がる。Keycloak の死活は監視（04）で扱う。

各確認には合計 3 秒の期限を設け、超えたものは ``unavailable`` とする。応答に接続エラーの詳細は含めない（ログに残す）。
"""
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from main_app.route.public.redis_client import get_public_redis
from modules.errors.openapi import problem_responses
from modules.tenancy.providers import get_app_runtime_engine, get_cp_runtime_engine

logger = logging.getLogger(__name__)

router = APIRouter()

# 依存先の確認にかける合計の期限（秒）
READY_TIMEOUT_SECONDS = 3.0

type CheckStatus = Literal["ok", "unavailable"]


class HealthLive(BaseModel):
    """liveness の応答。"""

    status: Literal["ok"] = Field(description="プロセスが応答できる")


class HealthReady(BaseModel):
    """readiness の応答。いずれかが `unavailable` なら全体も `unavailable`（HTTP 503）。"""

    status: CheckStatus = Field(description="全体の状態")
    checks: dict[str, CheckStatus] = Field(description="依存先ごとの状態（`cp_db` / `app_db` / `redis`）")


def _check_database(get_engine: Callable[[], Engine]) -> None:
    """DB に接続して `SELECT 1` を実行する。"""
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _check_redis() -> None:
    """Redis に `PING` する。"""
    get_public_redis().ping()


def run_checks(checks: dict[str, Callable[[], None]], timeout: float = READY_TIMEOUT_SECONDS) -> dict[str, CheckStatus]:
    """確認を並列に実行し、結果を返す。例外・期限切れは `unavailable`。

    Args:
        checks: 確認の名前と関数。
        timeout: 合計の期限（秒）。

    Returns:
        dict: 名前ごとの結果。
    """
    executor = ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="health-ready")
    try:
        futures = {name: executor.submit(check) for name, check in checks.items()}
        wait(futures.values(), timeout=timeout)
        results: dict[str, CheckStatus] = {}
        for name, future in futures.items():
            if not future.done():
                logger.warning("readiness check timed out: %s", name)
                results[name] = "unavailable"
            elif (error := future.exception()) is not None:
                logger.warning("readiness check failed: %s (%s)", name, type(error).__name__)
                results[name] = "unavailable"
            else:
                results[name] = "ok"
        return results
    finally:
        # 期限切れの確認の完了を待たない（接続待ちでブロックしているスレッドを残して応答する）
        executor.shutdown(wait=False, cancel_futures=True)


@router.get("/live", summary="liveness", responses=problem_responses())
def get_live() -> HealthLive:
    """プロセスが応答できることを返す（依存先は確認しない）。"""
    return HealthLive(status="ok")


@router.get(
    "/ready",
    summary="readiness",
    responses={503: {"model": HealthReady, "description": "依存先（CP DB・AP DB・Redis）のいずれかに接続できない"}},
)
def get_ready(response: Response) -> HealthReady:
    """CP DB・AP DB・Redis に接続できるかを確認する。

    全て接続できれば 200、いずれかが失敗・期限切れなら 503。Keycloak は確認しない（理由は実装のドキュメントを参照）。
    """
    checks = run_checks(
        {
            "cp_db": lambda: _check_database(get_cp_runtime_engine),
            "app_db": lambda: _check_database(get_app_runtime_engine),
            "redis": _check_redis,
        }
    )
    healthy = all(result == "ok" for result in checks.values())
    if not healthy:
        response.status_code = 503
    return HealthReady(status="ok" if healthy else "unavailable", checks=checks)
