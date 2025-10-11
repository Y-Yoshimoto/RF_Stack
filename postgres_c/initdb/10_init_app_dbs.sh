#!/usr/bin/env bash

# 環境変数を参照するため、shellスクリプトとして実行
set -xe

# アプリケーション用ユーザーの作成データベース生成と権限付与
# テナント用
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE USER "$APP_DB_USER" WITH ENCRYPTED PASSWORD '$APP_DB_PASSWORD';
	CREATE DATABASE "$APP_DB_NAME" OWNER "$APP_DB_USER";
	CREATE DATABASE "$CONTROL_PLANE_DB_NAME" OWNER "$APP_DB_USER";
	GRANT ALL PRIVILEGES ON DATABASE "$APP_DB_NAME" TO "$APP_DB_USER";
	GRANT ALL PRIVILEGES ON DATABASE "$CONTROL_PLANE_DB_NAME" TO "$APP_DB_USER";
EOSQL

# 後続のSQLの環境変数を置換する
sed -i "s|{{APP_DB_USER}}|$APP_DB_USER|g" /docker-entrypoint-initdb.d/*.sql
sed -i "s|{{APP_DB_NAME}}|$APP_DB_NAME|g" /docker-entrypoint-initdb.d/*.sql
sed -i "s|{{CONTROL_PLANE_DB_NAME}}|$CONTROL_PLANE_DB_NAME|g" /docker-entrypoint-initdb.d/*.sql