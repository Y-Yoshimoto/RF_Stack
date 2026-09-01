from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

# from sqlalchemy import create_engine

class DBConnector:
    """ DBコネクタクラス """

    def __init__(self, dbuser: str, dbpassword: str, dbhost: str, dbport: str, dbname: str):
        """ コンストラクタ """
        # DB接続情報の接続情報を保持
        self.endpoint = {
            "dbuser": dbuser,
            "dbpassword": dbpassword,
            "dbhost": dbhost,
            "dbport": dbport,
            "dbname": dbname,
            "url": f"postgresql://{dbuser}:{dbpassword}@{dbhost}:{dbport}/{dbname}"
        }
        # DBエンジンの作成
        self.engine = self.create_db_engine()
        # セッションメーカーの作成
        self.SessionDep = Annotated[Session, Depends(self.get_session)]

    def create_db_engine(self):
        """ DBエンジンの作成 """
        # 参考: https://docs.sqlalchemy.org/en/20/core/engines.html#postgresql
        return create_engine(self.endpoint["url"], echo=False)

    def create_db_and_tables(self):
        """ DBとテーブルの作成 """
        SQLModel.metadata.create_all(self.engine)

    def get_session(self):
        """ DBセッション取得 """
        with Session(self.engine) as session:
            yield session
