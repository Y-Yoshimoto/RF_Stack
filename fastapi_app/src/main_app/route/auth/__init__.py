"""route/auth パッケージの公開 API。

app.py にルーターを登録する際は次のように使用する::

    from main_app.route.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth")
"""
from .apiapp import router

__all__ = ["router"]
