#!/usr/bin/env python
# coding:utf-8
"""テナントコンテキストを設定する FastAPI Dependency を生成するモジュール。

:func:`create_tenant_context_dependency` にリゾルバを渡すと、認証済みユーザー情報から
テナントコンテキストを導出し、**リクエストの間だけ** ``contextvars`` に設定する
yield 依存関数を返す。終了時（例外時を含む）には必ず元に戻す。

使用例::

    from typing import Annotated
    from fastapi import Depends

    from modules.tenancy.context import TenantContext
    from modules.tenancy.dependency import create_tenant_context_dependency
    from modules.tenancy.registry import CachedTenantRegistry, SqlTenantRegistry
    from modules.tenancy.resolver import RegistryTenantResolver

    registry = CachedTenantRegistry(SqlTenantRegistry(cp_db.engine))
    get_tenant_context_dep = create_tenant_context_dependency(RegistryTenantResolver(registry))
    TenantDep = Annotated[TenantContext, Depends(get_tenant_context_dep)]

    @router.get("/todos")
    def list_todos(tenant: TenantDep, session: SessionDep): ...

    # ルータ全体に適用する場合
    router = APIRouter(dependencies=[Depends(get_tenant_context_dep)])

実装上の注意:
    依存関数は **async** の yield 依存として定義している。FastAPI は同期の yield 依存を
    スレッドプール内のコピーされた ``Context`` で実行するため、そこで設定した contextvar は
    エンドポイントに伝播しない。async の依存はリクエスト処理と同じタスク・同じ ``Context`` で
    開始・終了するため、設定がエンドポイント（同期エンドポイントのスレッドプール実行を含む）
    から参照でき、終了時の ``Token`` による復元も同じ ``Context`` で行える。
    リゾルバはレジストリ問い合わせ（ブロッキング I/O）を含みうるため、スレッドプールで呼ぶ。

エラーレスポンス:
    リゾルバが :class:`~modules.tenancy.resolver.TenantResolutionError` を送出した場合は
    403 とし、``detail`` に短いコード文字列（例: ``tenant_inactive``）を入れる。
    将来 RFC 9457 Problem Details に統一する際は、このコードを ``type`` / ``code`` に対応付ける。
"""
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from modules.auth.dependency import get_current_user

from .context import TenantContext, tenant_scope
from .resolver import TenantResolutionError, TenantResolver

# 依存関数の型（FastAPI の Depends に渡すもの）
type TenantContextDependency = Callable[..., AsyncIterator[TenantContext]]


def create_tenant_context_dependency(resolver: TenantResolver, user_dependency: Callable[..., Any] = get_current_user) -> TenantContextDependency:
    """テナントコンテキストを設定する FastAPI の yield 依存関数を生成する。

    Args:
        resolver: 認証済みユーザー情報からテナントコンテキストを導出する関数。
            拒否する場合は :class:`~modules.tenancy.resolver.TenantResolutionError` を送出する。
            同期関数として呼び出す（スレッドプールで実行される）。
        user_dependency: 認証済みユーザー情報（dict）を返す依存関数。既定は
            :func:`modules.auth.dependency.get_current_user`。未認証時の 401 はこちらが返す。
            テストでは ``app.dependency_overrides[get_current_user]`` で差し替えるか、
            本引数にフェイクを渡す。

    Returns:
        TenantContextDependency: ``Depends`` に渡す async の yield 依存関数。
        :class:`~modules.tenancy.context.TenantContext` を yield する。
    """

    async def tenant_context_dependency(user: Annotated[Mapping[str, Any], Depends(user_dependency)]) -> AsyncIterator[TenantContext]:
        """認証済みユーザーのテナントコンテキストをリクエスト中だけ設定する。

        Raises:
            HTTPException(403): テナントが未登録・非 ACTIVE・レルムとテナント ID の不一致など、
                リゾルバが拒否した場合。``detail`` は失敗理由のコード文字列。
        """
        try:
            ctx = await run_in_threadpool(resolver, user)
        except TenantResolutionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.code.value) from exc

        with tenant_scope(ctx):
            yield ctx

    return tenant_context_dependency
