#!/usr/bin/env bash
# =============================================================================
# プレーン毎のデータベースとロールの初期化
#
#   コントロールプレーン  : CONTROL_PLANE_DB_NAME (control_plane_db)
#     cp_owner            DB / public スキーマの所有者。マイグレーション専用
#     cp_runtime          CONNECT + テーブル DML + シーケンス USAGE/SELECT
#     cp_registry_reader  CONNECT + スキーマ USAGE のみ
#                         (v_tenant_registry 作成時のマイグレーションで SELECT を個別付与する)
#
#   アプリケーションプレーン : APP_DB_NAME (app_db)
#     app_owner           DB / public スキーマの所有者。マイグレーション専用
#     app_runtime         CONNECT + テーブル DML + シーケンス USAGE/SELECT (RLS 適用)
#     app_cp_agent        CONNECT + テーブル SELECT/DELETE のみ (RLS 適用)
#
# - 全ロール NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS。RLS をバイパスするロールは作らない。
# - 各ロールは自プレーンの DB にのみ CONNECT できる (postgres / template1 / runtime_db も PUBLIC から CONNECT を剥奪)。
# - 環境変数は psql 変数 (-v) として渡し、SQL インジェクションとパスワードのログ出力を避ける。
# =============================================================================

# パスワードがログに出ないよう xtrace (-x) は使わない
set -euo pipefail

# ロール名の既定値 (ロール名そのもの)
: "${CP_DB_OWNER_USER:=cp_owner}"
: "${CP_DB_RUNTIME_USER:=cp_runtime}"
: "${CP_DB_REGISTRY_READER_USER:=cp_registry_reader}"
: "${APP_DB_OWNER_USER:=app_owner}"
: "${APP_DB_RUNTIME_USER:=app_runtime}"
: "${APP_DB_CP_AGENT_USER:=app_cp_agent}"
# データベース名の既定値
: "${CONTROL_PLANE_DB_NAME:=control_plane_db}"
: "${APP_DB_NAME:=app_db}"

# 初期化スクリプトの確認
ls -al /docker-entrypoint-initdb.d/
# 後続のSQLの環境変数を置換する (パスワードは置換対象にしない)
sed -i "s|{{CONTROL_PLANE_DB_NAME}}|${CONTROL_PLANE_DB_NAME}|g" /docker-entrypoint-initdb.d/*.sql
sed -i "s|{{APP_DB_NAME}}|${APP_DB_NAME}|g" /docker-entrypoint-initdb.d/*.sql
sed -i "s|{{CP_DB_OWNER_USER}}|${CP_DB_OWNER_USER}|g" /docker-entrypoint-initdb.d/*.sql
sed -i "s|{{APP_DB_OWNER_USER}}|${APP_DB_OWNER_USER}|g" /docker-entrypoint-initdb.d/*.sql

# --only-sedオプションの確認
if [[ " $* " =~ " --only-sed " ]]; then
	echo "--only-sed is enabled. Exiting without initializing databases."
	exit 0
else
	echo "--only-sed is disabled. Continuing database initialization."
fi

# パスワードは必須 (空のパスワードはログイン不能なロールになるため、ここで失敗させる)
: "${CP_DB_OWNER_PASSWORD:?CP_DB_OWNER_PASSWORD is required}"
: "${CP_DB_RUNTIME_PASSWORD:?CP_DB_RUNTIME_PASSWORD is required}"
: "${CP_DB_REGISTRY_READER_PASSWORD:?CP_DB_REGISTRY_READER_PASSWORD is required}"
: "${APP_DB_OWNER_PASSWORD:?APP_DB_OWNER_PASSWORD is required}"
: "${APP_DB_RUNTIME_PASSWORD:?APP_DB_RUNTIME_PASSWORD is required}"
: "${APP_DB_CP_AGENT_PASSWORD:?APP_DB_CP_AGENT_PASSWORD is required}"

echo "Creating roles: ${CP_DB_OWNER_USER}, ${CP_DB_RUNTIME_USER}, ${CP_DB_REGISTRY_READER_USER}, ${APP_DB_OWNER_USER}, ${APP_DB_RUNTIME_USER}, ${APP_DB_CP_AGENT_USER}"
echo "Creating databases: ${CONTROL_PLANE_DB_NAME}, ${APP_DB_NAME}"

# ヒアドキュメントはクォートしてシェル展開を無効化し、値は psql 変数で埋め込む
#   :"var" -> 識別子としてクォート, :'var' -> リテラルとしてクォート
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
	-v cp_db="$CONTROL_PLANE_DB_NAME" \
	-v cp_owner="$CP_DB_OWNER_USER" \
	-v cp_owner_password="$CP_DB_OWNER_PASSWORD" \
	-v cp_runtime="$CP_DB_RUNTIME_USER" \
	-v cp_runtime_password="$CP_DB_RUNTIME_PASSWORD" \
	-v cp_registry_reader="$CP_DB_REGISTRY_READER_USER" \
	-v cp_registry_reader_password="$CP_DB_REGISTRY_READER_PASSWORD" \
	-v app_db="$APP_DB_NAME" \
	-v app_owner="$APP_DB_OWNER_USER" \
	-v app_owner_password="$APP_DB_OWNER_PASSWORD" \
	-v app_runtime="$APP_DB_RUNTIME_USER" \
	-v app_runtime_password="$APP_DB_RUNTIME_PASSWORD" \
	-v app_cp_agent="$APP_DB_CP_AGENT_USER" \
	-v app_cp_agent_password="$APP_DB_CP_AGENT_PASSWORD" \
	<<-'EOSQL'
	-- -------------------------------------------------------------------------
	-- ロール作成 (いずれも特権なし・RLS バイパスなし)
	-- -------------------------------------------------------------------------
	CREATE ROLE :"cp_owner" WITH LOGIN PASSWORD :'cp_owner_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
	CREATE ROLE :"cp_runtime" WITH LOGIN PASSWORD :'cp_runtime_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
	CREATE ROLE :"cp_registry_reader" WITH LOGIN PASSWORD :'cp_registry_reader_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
	CREATE ROLE :"app_owner" WITH LOGIN PASSWORD :'app_owner_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
	CREATE ROLE :"app_runtime" WITH LOGIN PASSWORD :'app_runtime_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
	CREATE ROLE :"app_cp_agent" WITH LOGIN PASSWORD :'app_cp_agent_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

	-- -------------------------------------------------------------------------
	-- データベース作成と CONNECT 権限 (PUBLIC からは剥奪し、自プレーンのロールのみ許可)
	-- -------------------------------------------------------------------------
	CREATE DATABASE :"cp_db" OWNER :"cp_owner";
	REVOKE ALL ON DATABASE :"cp_db" FROM PUBLIC;
	GRANT CONNECT ON DATABASE :"cp_db" TO :"cp_runtime", :"cp_registry_reader";

	CREATE DATABASE :"app_db" OWNER :"app_owner";
	REVOKE ALL ON DATABASE :"app_db" FROM PUBLIC;
	GRANT CONNECT ON DATABASE :"app_db" TO :"app_runtime", :"app_cp_agent";

	-- 既定 DB と動作確認用の runtime_db (00_setup_runtime.sql) にもプレーンのロールが接続できないようにする
	-- (いずれも superuser の postgres のみが使う。DB 自体はそのまま残す)
	REVOKE CONNECT, TEMPORARY ON DATABASE postgres FROM PUBLIC;
	REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC;
	REVOKE CONNECT, TEMPORARY ON DATABASE runtime_db FROM PUBLIC;

	-- -------------------------------------------------------------------------
	-- コントロールプレーン DB
	-- -------------------------------------------------------------------------
	\connect :"cp_db"
	-- public スキーマは owner のみが所有・CREATE できる
	ALTER SCHEMA public OWNER TO :"cp_owner";
	REVOKE ALL ON SCHEMA public FROM PUBLIC;
	GRANT USAGE ON SCHEMA public TO :"cp_runtime", :"cp_registry_reader";
	-- cp_owner が今後作成するテーブル・シーケンスへの既定権限
	ALTER DEFAULT PRIVILEGES FOR ROLE :"cp_owner" IN SCHEMA public
		GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"cp_runtime";
	ALTER DEFAULT PRIVILEGES FOR ROLE :"cp_owner" IN SCHEMA public
		GRANT USAGE, SELECT ON SEQUENCES TO :"cp_runtime";
	-- cp_registry_reader には既定権限を付与しない
	-- (v_tenant_registry 作成時のマイグレーションで GRANT SELECT を個別に行う)

	-- -------------------------------------------------------------------------
	-- アプリケーションプレーン DB
	-- -------------------------------------------------------------------------
	\connect :"app_db"
	ALTER SCHEMA public OWNER TO :"app_owner";
	REVOKE ALL ON SCHEMA public FROM PUBLIC;
	GRANT USAGE ON SCHEMA public TO :"app_runtime", :"app_cp_agent";
	-- app_owner が今後作成するテーブル・シーケンスへの既定権限
	ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner" IN SCHEMA public
		GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_runtime";
	ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner" IN SCHEMA public
		GRANT USAGE, SELECT ON SEQUENCES TO :"app_runtime";
	-- app_cp_agent はメトリクス集計とテナント物理削除のみ (シーケンス権限なし)
	ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner" IN SCHEMA public
		GRANT SELECT, DELETE ON TABLES TO :"app_cp_agent";
	EOSQL
echo "Database initialization completed."
