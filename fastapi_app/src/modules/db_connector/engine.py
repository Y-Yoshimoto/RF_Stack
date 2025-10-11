# from typing import Annotated

# from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlmodel import text
# from sqlalchemy import create_engine

def create_db_engine(dbuser: str, dbpassword: str, dbhost: str, dbport: str, dbname: str):
    """ DBエンジンの作成 """
    # 参考: https://docs.sqlalchemy.org/en/20/core/engines.html#postgresql
    postgresql_url = f"postgresql://{dbuser}:{dbpassword}@{dbhost}:{dbport}/{dbname}"
    return create_engine(postgresql_url, echo=False)


# 直接実行/動作確認用
if __name__ == "__main__":
    # 環境変数読み込み
    import os
    from dotenv import load_dotenv
    load_dotenv()
    dbuser = os.getenv("DB_USER", "postgres")
    dbpassword = os.getenv("DB_PASSWORD", "postgres")
    dbhost = os.getenv("DB_HOST", "postgres_c")
    dbport = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "runtime_db")
    postgresql_url = f"postgresql://{dbuser}:{dbpassword}@{dbhost}:{dbport}/{dbname}"
    engine = create_db_engine(dbuser, dbpassword, dbhost, dbport, dbname)

    # runtime_tableの全件取得
    with Session(engine) as session:
        query = text("SELECT * FROM runtime_table;")
        print(query)
        result = session.exec(query)
        for row in result:
            print(row)