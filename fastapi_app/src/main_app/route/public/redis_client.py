#!/usr/bin/env python
# coding:utf-8
"""公開 API（ヘルスチェック・レート制限）用の Redis クライアント。

セッション用のクライアント（``modules.auth.session``）とは別に、ログイン前の公開 API が Redis の障害で
長くブロックされないよう、接続・読み書きに短いタイムアウト（1 秒）を設定したクライアントを使う。
接続先は同じ環境変数 ``REDIS_URL``（既定 ``redis://redis_c:6379/0``）。
"""
import os
from functools import lru_cache

from redis import Redis

# 接続・読み書きのタイムアウト（秒）
REDIS_TIMEOUT_SECONDS = 1.0


@lru_cache(maxsize=1)
def _client_for(redis_url: str) -> Redis:
    """接続 URL ごとにクライアント（コネクションプール）を作ってキャッシュする。"""
    return Redis.from_url(redis_url, decode_responses=True, socket_timeout=REDIS_TIMEOUT_SECONDS, socket_connect_timeout=REDIS_TIMEOUT_SECONDS)


def get_public_redis() -> Redis:
    """公開 API 用の Redis クライアントを返す（FastAPI の依存関数としても使える）。

    Returns:
        Redis: タイムアウト付きのクライアント。
    """
    return _client_for(os.getenv("REDIS_URL", "redis://redis_c:6379/0"))
