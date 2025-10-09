#!/usr/bin/env python
# coding:utf-8
# import multiprocessing

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
# ホットリロード
reload=True
# タイムアウト
timeout = 10
