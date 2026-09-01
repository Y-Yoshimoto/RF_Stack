# SQLモデル定義
from datetime import datetime

from sqlmodel import Column, DateTime, Field, SQLModel, text

# ユーティリティモジュールをインポート
from modules.utils import generate_uuid


# テナント情報テーブルモデル
class TTenant(SQLModel, table=True):
    """ テナント情報テーブル """
    __table_args__ = {"comment": "テナント情報テーブル"}
    __tablename__ = "t_tenant"
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
    # tier: str = Field(
    #     description="ティアフラグ",
    #     default="normal")
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
