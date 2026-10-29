import os
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Self

from fastapi import Depends
from sqlalchemy import URL, Engine
from sqlmodel import Session, create_engine

# from sqlalchemy import create_engine

class DBConnector:
    """ DBコネクタクラス

        DB 接続（エンジン生成）の唯一の入口。``create_engine`` は本クラス以外で呼ばない。
        エンジンを生成するだけでは DB に接続しない（最初のクエリ実行時に接続する）。
    """

    def __init__(self, dbuser: str, dbpassword: str, dbhost: str, dbport: str, dbname: str, *, engine_options: Mapping[str, Any] | None = None):
        """ コンストラクタ

            dbuser / dbpassword / dbhost / dbport / dbname: 接続情報
            engine_options: ``create_engine`` に渡す追加オプション（例: ``{"pool_pre_ping": True}``）
        """
        # DB接続情報の接続情報を保持
        # url はパスワードの記号を正しくエスケープするため URL.create で組み立てる（repr ではパスワードがマスクされる）
        self.endpoint = {
            "dbuser": dbuser,
            "dbpassword": dbpassword,
            "dbhost": dbhost,
            "dbport": dbport,
            "dbname": dbname,
            "url": URL.create("postgresql", username=dbuser, password=dbpassword, host=dbhost, port=int(dbport), database=dbname),
        }
        self._engine_options: dict[str, Any] = dict(engine_options or {})
        # DBエンジンの作成
        self.engine = self.create_db_engine()
        # セッションメーカーの作成
        self.SessionDep = Annotated[Session, Depends(self.get_session)]

    @classmethod
    def from_env(cls, user_env: str, password_env: str, dbname_env: str, *, host_env: str = "DB_HOST", port_env: str = "DB_PORT", engine_options: Mapping[str, Any] | None = None) -> Self:
        """ 環境変数の名前を指定して生成する

            user_env / password_env / dbname_env: ユーザー名・パスワード・DB 名を持つ環境変数の名前
            host_env / port_env: ホスト・ポートを持つ環境変数の名前
            engine_options: ``create_engine`` に渡す追加オプション
            return: DBConnector
            raise: RuntimeError 環境変数が未設定・空の場合（メッセージには変数名のみを含め、値は含めない）
        """
        names = (user_env, password_env, host_env, port_env, dbname_env)
        values = {name: os.environ.get(name, "") for name in names}
        missing = [name for name in names if not values[name]]
        if missing:
            raise RuntimeError(f"DB 接続の環境変数が設定されていません: {', '.join(missing)}")
        return cls(
            dbuser=values[user_env],
            dbpassword=values[password_env],
            dbhost=values[host_env],
            dbport=values[port_env],
            dbname=values[dbname_env],
            engine_options=engine_options,
        )

    def create_db_engine(self) -> Engine:
        """ DBエンジンの作成 """
        # 参考: https://docs.sqlalchemy.org/en/20/core/engines.html#postgresql
        return create_engine(self.endpoint["url"], echo=False, **self._engine_options)

    def get_session(self) -> Iterator[Session]:
        """ DBセッション取得 """
        with Session(self.engine) as session:
            yield session
