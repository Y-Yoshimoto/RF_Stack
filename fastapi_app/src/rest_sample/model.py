
from typing import Optional

from pydantic import BaseModel, Field


class SampleData(BaseModel):
    # サンプルデータ
    id: int = Field(None, description="ID")
    name: Optional[str] = Field('sample', description="名前")
    date: Optional[str] = Field('2024-02-27', description="日付 yyyy-mm-dd形式")
