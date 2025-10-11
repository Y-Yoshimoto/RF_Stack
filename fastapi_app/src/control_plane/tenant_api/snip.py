# snip.py
from datetime import datetime
from sqlmodel import Column, DateTime
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlmodel import text

# ユーティリティモジュールをインポート
from modules.utils import generate_uuid

# DB接続用のモジュールをインポート
from modules.db_connector.engine import create_db_engine

# モデル/table定義
class M_Tenant(SQLModel, table=True, table_args={"comment": "テナント情報テーブル"}):
    """ テナント情報テーブル """
    id: str = Field(
        description="テナントID",
        default_factory=generate_uuid, unique=True, primary_key=True, index=True)
    name: str = Field(
        description="テナント名",
        index=True)
    isenabled: bool = Field(
        description="有効フラグ",
        default=True)
    claim: bool = Field(
        description="請求フラグ",
        default=False)
    external_id: str | None = Field(
        description="外部システムと接続するためのID",
        default=None)
    industry: str | None = Field(
        description="業種区分",
        default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.now)
    )

def create_db_and_tables(engine):
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
    engine = create_db_engine(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME)

    # DBとテーブル作成
    create_db_and_tables(engine)

    # # runtime_tableの全件取得
    # with Session(engine) as session:
    #     query = text("SELECT * FROM runtime_table;")
    #     print(query)
    #     result = session.exec(query)
    #     for row in result:
    #         print(row)