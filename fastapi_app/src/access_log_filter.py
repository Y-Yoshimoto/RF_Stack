#!/usr/bin/env python
# coding:utf-8
"""アクセスログから機微なクエリ文字列を除くフィルタ（docs/architecture/03-conventions.md 6.2）。

uvicorn のアクセスログは ``'%s - "%s %s HTTP/%s" %d'`` の形式で、引数の 3 番目にクエリ付きのパスを持つ。
``/api/auth/callback?code=...&state=...`` のように認可コード・state がそのまま残るため、ログに出る前に伏せる。

- ``/api/auth/`` 配下: クエリ文字列を全て除く（認証フローのパラメータは全て機微として扱う）
- それ以外: キー名が機微（code / state / token / password / secret 等）の値だけ ``***`` にする

適用方法:
    - uvicorn: ``--log-config ./src/uvicorn_log_config.json``（``uvicorn.access`` のハンドラにこのフィルタを付ける）
    - gunicorn: ``gunicorn.conf.py`` の ``logconfig_dict`` で、アクセスログのハンドラに付ける
"""
import logging
import re
from urllib.parse import parse_qsl, urlencode

# クエリを丸ごと除くパスの接頭辞
REDACT_ALL_QUERY_PREFIXES = ("/api/auth/",)
# 値を伏せるキー名の部分一致(小文字)
SENSITIVE_KEY_PATTERN = re.compile(r"code|state|token|password|passwd|secret|session|sid|authorization|api_key|apikey", re.IGNORECASE)
MASK = "***"
# uvicorn.access の引数: (client_addr, method, full_path, http_version, status_code)
_PATH_ARG_INDEX = 2


def redact_path(full_path: str) -> str:
    """クエリ付きのパスから機微な情報を除く。

    Args:
        full_path: ``/path?query`` 形式の文字列。

    Returns:
        str: クエリを除いた、または機微な値を伏せたパス。クエリが無ければそのまま。
    """
    path, sep, query = full_path.partition("?")
    if not sep:
        return full_path
    if path.startswith(REDACT_ALL_QUERY_PREFIXES):
        return path
    pairs = parse_qsl(query, keep_blank_values=True)
    if not any(SENSITIVE_KEY_PATTERN.search(key) for key, _ in pairs):
        return full_path
    masked = [(key, MASK if SENSITIVE_KEY_PATTERN.search(key) else value) for key, value in pairs]
    # "***" をエスケープせず読みやすく出す
    return f"{path}?{urlencode(masked, safe='*')}"


class RedactAccessQueryFilter(logging.Filter):
    """アクセスログのパス引数から機微なクエリを除くフィルタ。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """ログレコードのパス引数を書き換える（レコードは常に通す）。

        Args:
            record: ログレコード。

        Returns:
            bool: 常に ``True``。
        """
        args = record.args
        if isinstance(args, tuple) and len(args) > _PATH_ARG_INDEX and isinstance(args[_PATH_ARG_INDEX], str):
            record.args = (*args[:_PATH_ARG_INDEX], redact_path(args[_PATH_ARG_INDEX]), *args[_PATH_ARG_INDEX + 1 :])
        return True
