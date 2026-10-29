"""auth パッケージの公開 API (BFF 認証。プレーン別)。

各エンドポイントに次のように使用する::

    from fastapi import Depends
    from modules.auth import get_current_app_user, require_cp_roles

    @router.get("/me")
    def me(user: dict = Depends(get_current_app_user)):
        return {"user": user}

    @router.post("/cp/tenants")
    def create_tenant(user: dict = Depends(require_cp_roles("saas_admin"))):
        ...

変更系エンドポイントには CSRF 対策 (:func:`require_csrf_protection`) も付ける。
``get_current_user`` は移行期間中の別名 (= ``get_current_app_user``)。
"""
from .csrf import require_csrf_protection
from .dependency import get_current_app_user, get_current_cp_user, get_current_user, require_app_roles, require_cp_roles
from .plane import Plane

__all__ = [
    "Plane",
    "get_current_app_user",
    "get_current_cp_user",
    "get_current_user",
    "require_app_roles",
    "require_cp_roles",
    "require_csrf_protection",
]
