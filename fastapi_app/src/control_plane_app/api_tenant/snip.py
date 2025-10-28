# snip.py
from datetime import datetime
from sqlmodel import Column, DateTime
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlmodel import text

# DB接続用のモジュールをインポート
from modules.db_connector.engine import DBConnector

# モデルインポート
# from control_plane.models.sql_models import * # noqa: F403, F401

def create_db_and_tables(engine):
    """ DBとテーブル作成 """
    SQLModel.metadata.create_all(engine)

# 直接実行用
if __name__ == "__main__":
    # 環境変数読み込み
    import os
    from dotenv import load_dotenv
    load_dotenv()
    DB_USER = os.environ["APP_DB_USER"]
    DB_PASSWORD = os.environ["APP_DB_PASSWORD"]
    DB_HOST = os.environ["DB_HOST"]
    DB_PORT = os.environ["DB_PORT"]
    DB_NAME = os.environ["CONTROL_PLANE_DB_NAME"]
    print(f"DB_USER: {DB_USER}, DB_PASSWORD: {DB_PASSWORD}, DB_HOST: {DB_HOST}, DB_PORT: {DB_PORT}, DB_NAME: {DB_NAME}")
    db_connector = DBConnector(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME)
    engine = db_connector.engine

    # DBとテーブル作成
    create_db_and_tables(engine)

    # # runtime_tableの全件取得
    # with Session(engine) as session:
    #     query = text("SELECT * FROM runtime_table;")
    #     print(query)
    #     result = session.exec(query)
    #     for row in result:
    #         print(row)