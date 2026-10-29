#!/usr/bin/env python
# coding:utf-8
# import multiprocessing
import os

from access_log_filter import RedactAccessQueryFilter

# アプリケーション指定
wsgi_app = 'app:app'
# ワーカークラス指定
worker_class = "uvicorn.workers.UvicornWorker"
# IPポートバインド
bind = "0.0.0.0:8000"
# 実行ワーカー数
workers = 2
#workers = multiprocessing.cpu_count() * 1 + 1
# デーモン無効
daemon = False
# ホットリロード(開発専用。APP_ENV=development のときだけ有効。本番では無効)
reload = os.getenv("APP_ENV", "development").strip().lower() == "development"
# タイムアウト(秒)。ワーカーが応答しないと判断して再起動するまでの時間。
# テナント払い出し API は同期で最大 30 秒かかるため(01 CP-ONB-06「API サーバーのタイムアウトは 30 秒より長く」)、30 秒より長くする。
# リバースプロキシ(nginx の proxy_read_timeout 等)もこれ以上にすること。環境変数 GUNICORN_TIMEOUT で上書きできる。
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
# 停止シグナル受信後、処理中のリクエストを待つ時間(秒)
graceful_timeout = 30
# アクセスログを標準出力に出す。認可コードを含むクエリ(/api/auth/callback?code=...)は access_log_filter で除く
accesslog = "-"
# gunicorn は logconfig_dict を既定値に浅くマージするため、handlers / formatters / loggers は全て指定する
logconfig_dict = {
    "root": {"level": "INFO", "handlers": ["error_console"]},
    "filters": {"redact_access_query": {"()": RedactAccessQueryFilter}},
    "formatters": {
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter",
        },
    },
    "handlers": {
        "error_console": {"class": "logging.StreamHandler", "formatter": "generic", "stream": "ext://sys.stderr"},
        "access_console": {"class": "logging.StreamHandler", "formatter": "generic", "stream": "ext://sys.stdout", "filters": ["redact_access_query"]},
    },
    "loggers": {
        "gunicorn.error": {"level": "INFO", "handlers": ["error_console"], "propagate": False, "qualname": "gunicorn.error"},
        # UvicornWorker は uvicorn.access のハンドラをこのロガーのハンドラに差し替える
        "gunicorn.access": {"level": "INFO", "handlers": ["access_console"], "propagate": False, "qualname": "gunicorn.access"},
    },
}
