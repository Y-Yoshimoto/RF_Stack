from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
config = context.config
# モデルをインポート
from control_plane.models.sql_models import *  # noqa: F403 # モデルをすべてインポート
## SQLModelのメタデータをターゲットに設定
from sqlmodel import SQLModel
target_metadata = SQLModel.metadata 

# 環境変数の読み込みとセット
import os
from dotenv import load_dotenv
load_dotenv()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
# target_metadata = None

# def run_migrations_offline() -> None:
#     """ オフラインモードマイグレーション """
#     url = config.get_main_option("sqlalchemy.url")
#     context.configure(
#         url=url,
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#     )

#     with context.begin_transaction():
#         context.run_migrations()


def run_migrations_online() -> None:
    """ オンラインモードマイグレーション """
    # 環境変数をalembic設定にセット
    config.set_section_option("alembic", "APP_DB_USER", os.environ.get("APP_DB_USER"))
    config.set_section_option("alembic", "APP_DB_PASSWORD", os.environ.get("APP_DB_PASSWORD"))
    config.set_section_option("alembic", "DB_HOST", os.environ.get("DB_HOST"))
    config.set_section_option("alembic", "DB_PORT", os.environ.get("DB_PORT"))
    config.set_section_option("alembic", "CONTROL_PLANE_DB_NAME", os.environ.get("CONTROL_PLANE_DB_NAME"))
    print(f"Loaded environment variables: APP_DB_USER={os.environ.get('APP_DB_USER')}, APP_DB_PASSWORD={'***' if os.environ.get('APP_DB_PASSWORD') else None}, DB_HOST={os.environ.get('DB_HOST')}, DB_PORT={os.environ.get('DB_PORT')}, CONTROL_PLANE_DB_NAME={os.environ.get('CONTROL_PLANE_DB_NAME')}")
    # DB接続情報をalembic設定から取得してエンジン作成
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    print(f"connectable: {connectable}")

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
