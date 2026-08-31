"""route/auth \u30d1\u30c3\u30b1\u30fc\u30b8\u306e\u516c\u958b API\u3002

app.py \u306b\u30eb\u30fc\u30bf\u30fc\u3092\u767b\u9332\u3059\u308b\u969b\u306f\u6b21\u306e\u3088\u3046\u306b\u4f7f\u7528\u3059\u308b::\n\n    from main_app.route.auth import router as auth_router\n    app.include_router(auth_router, prefix=\"/api/auth\")\n"""
from .apiapp import router

__all__ = ["router"]
