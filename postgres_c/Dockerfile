# https://hub.docker.com/_/postgres
# postgres:18テンプレート
FROM postgres:18-trixie 
LABEL maintainer="y.yoshimoto"
# PostgreSQLの設定
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# 設定ファイルのコピー
# sample: /usr/share/postgresql/postgresql.conf.sample
# COPY postgresql.conf /etc/postgresql/postgresql.conf

# 初期構築データのコピー
COPY ./startup.sql /docker-entrypoint-initdb.d/startup.sql
