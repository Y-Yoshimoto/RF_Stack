#!/usr/bin/env python
# coding:utf-8
"""公開 API の簡易レート制限（Redis の固定ウィンドウ。01 §10.2）。

テナント存在確認 API でのテナント列挙を抑えるための簡易な実装。クライアントの IP アドレス単位で、
ウィンドウ内のリクエスト数を数える。

- ウィンドウの最初のリクエストで ``SET key 0 EX <window> NX`` してから ``INCR`` する（``MULTI`` で原子的に実行）。
  有効期限の無いキーが残らない。
- 上限を超えたら 429（``Retry-After`` 付き）。
- **Redis に接続できないときは制限せずに通す（fail-open）**。ログイン画面を Redis の障害に巻き込まないため。
  ただし障害は WARNING で記録する。

環境変数:
    PUBLIC_TENANT_LOOKUP_RATE_LIMIT: ウィンドウ内に許可するリクエスト数。既定 60。``0`` で無効。
    PUBLIC_TENANT_LOOKUP_RATE_WINDOW_SECONDS: ウィンドウの秒数。既定 60。

制約:
    クライアントの IP は ``request.client.host`` を使う。リバースプロキシ（Vite の proxy・nginx）の背後では、
    プロキシ側で ``X-Forwarded-For`` を設定し、uvicorn を ``--proxy-headers --forwarded-allow-ips=<プロキシの IP>`` で
    起動しないと、全クライアントが同じ IP（プロキシ）に見えて 1 つの枠を共有する。本番投入前に infra 側で設定すること。
    また固定ウィンドウのため、ウィンドウの境目で最大 2 倍のリクエストが通る。
"""
import logging
import os
from typing import Annotated

from fastapi import Depends, Request
from redis import Redis
from redis.exceptions import RedisError

from main_app.route.public.redis_client import get_public_redis
from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 60
DEFAULT_WINDOW_SECONDS = 60
_KEY_PREFIX = "rate_limit:public_tenant_lookup:"


def _env_int(name: str, default: int, *, minimum: int) -> int:
    """環境変数を整数で読む。不正な値・下限未満は既定値にする。"""
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value >= minimum else default


def get_limit() -> int:
    """ウィンドウ内に許可するリクエスト数を返す（0 なら制限しない）。"""
    return _env_int("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", DEFAULT_LIMIT, minimum=0)


def get_window_seconds() -> int:
    """ウィンドウの秒数を返す。"""
    return _env_int("PUBLIC_TENANT_LOOKUP_RATE_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS, minimum=1)


def limit_tenant_lookup(request: Request, redis: Annotated[Redis, Depends(get_public_redis)]) -> None:
    """テナント存在確認 API のレート制限を適用する FastAPI 依存関数。

    Args:
        request: リクエスト（クライアントの IP を使う）。
        redis: Redis クライアント。

    Raises:
        ProblemError(429): ウィンドウ内の上限を超えた場合。
    """
    limit = get_limit()
    if limit == 0:
        return
    window = get_window_seconds()
    client_host = request.client.host if request.client else "unknown"
    key = f"{_KEY_PREFIX}{client_host}"
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.set(key, 0, ex=window, nx=True)
        pipe.incr(key)
        pipe.ttl(key)
        _, count, ttl = pipe.execute()
    except RedisError:
        logger.warning("rate limit skipped: redis unavailable (fail-open)", exc_info=True)
        return
    if count > limit:
        retry_after = ttl if isinstance(ttl, int) and ttl > 0 else window
        raise problem_from_text(429, "too_many_requests", text_for_code("too_many_requests", 429), headers={"Retry-After": str(retry_after)})
