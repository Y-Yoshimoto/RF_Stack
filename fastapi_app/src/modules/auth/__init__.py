"""auth パッケージの公開 API。

各エンドポイントに次のように使用する::

    from modules.auth import get_current_user
    from fastapi import Depends

    @router.get("/protected")
    def protected(user: dict = Depends(get_current_user)):
        return {"user": user}
"""
from .dependency import get_current_user

__all__ = ["get_current_user"]
