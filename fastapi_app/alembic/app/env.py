""" Alembic 環境: アプリケーションプレーン DB(APP_DB_NAME)

    接続ロールは所有者ロール(APP_DB_OWNER_USER)。マイグレーション専用で、アプリ実行時には使わない。
    target_metadata はアプリケーションプレーン専用の MetaData(`app_plane_metadata`)。
    コントロールプレーンのモデルを import しても、ここには載らない。

    テナントスコープのテーブルを作成するリビジョンでは、`modules.tenancy.rls.enable_tenant_rls()` で
    RLS を設定すること(autogenerate はポリシーを検出しない)。
    テーブルは FORCE ROW LEVEL SECURITY のため、所有者ロールでも app.current_tenant 未設定では 0 件に見える。
    データ移行を行うリビジョンでは、テナント毎に set_config('app.current_tenant', ..., true) を設定して操作する。
"""
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, pool

from alembic import context

# モデルをインポート
# **新しいモデルモジュールは main_app/models/__init__.py で import する。**
# import 漏れのモデルは MetaData に載らず、autogenerate が DROP TABLE を生成する原因になる。
from main_app.models import app_plane_metadata

config = context.config
# アプリケーションプレーン専用の MetaData をターゲットに設定
target_metadata = app_plane_metadata

# 環境変数の読み込み(既に設定済みの環境変数は上書きしない)
load_dotenv()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _require_env(name: str) -> str:
    """ 必須の環境変数を取得する(値はログに出さない) """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"環境変数 {name} が設定されていません")
    return value


def get_database_url() -> URL:
    """ 環境変数から接続 URL を組み立てる(パスワードは URL.create がエスケープする) """
    return URL.create(
        drivername="postgresql+psycopg2",
        username=_require_env("APP_DB_OWNER_USER"),
        password=_require_env("APP_DB_OWNER_PASSWORD"),
        host=_require_env("DB_HOST"),
        port=int(_require_env("DB_PORT")),
        database=_require_env("APP_DB_NAME"),
    )


def run_migrations_offline() -> None:
    """ オフラインモードマイグレーション(SQL を出力するのみで接続しない) """
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """ オンラインモードマイグレーション """
    url = get_database_url()
    # パスワードはマスクして出力する
    print(f"Alembic(app) target: {url.render_as_string(hide_password=True)}")
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
