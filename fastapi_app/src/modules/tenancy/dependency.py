#!/usr/bin/env python
# coding:utf-8
"""テナントコンテキストを設定する FastAPI Dependency を生成するモジュール。

:func:`create_tenant_context_dependency` にリゾルバを渡すと、認証済みユーザー情報から
テナントコンテキストを導出し、**リクエストの間だけ** ``contextvars`` に設定する
yield 依存関数を返す。終了時（例外時を含む）には必ず元に戻す。

使用例::

    # アプリケーションプレーンでは組み立て済みの依存関数を使う（modules.tenancy.app_dependency）
    from modules.tenancy.app_dependency import AppSessionDep, AppTenantContextDep

    @router.get("/todos")
    def list_todos(tenant: AppTenantContextDep, session: AppSessionDep): ...

    # 独自に組み立てる場合
    from modules.tenancy.dependency import create_registry_tenant_context_dependency, create_tenant_context_dependency
    from modules.tenancy.providers import get_tenant_registry

    # レジストリを Depends で取得する（app.dependency_overrides[get_tenant_registry] で差し替えられる）
    get_tenant_context_dep = create_registry_tenant_context_dependency(get_tenant_registry, user_dependency=get_current_app_user)
    # 任意のリゾルバを使う
    get_tenant_context_dep = create_tenant_context_dependency(resolver, user_dependency=get_current_app_user)

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
from .registry import TenantRegistry
from .resolver import RegistryTenantResolver, TenantResolutionError, TenantResolver

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
        ctx = await _resolve_or_403(resolver, user)
        with tenant_scope(ctx):
            yield ctx

    return tenant_context_dependency


def create_registry_tenant_context_dependency(registry_dependency: Callable[..., TenantRegistry], user_dependency: Callable[..., Any] = get_current_user) -> TenantContextDependency:
    """テナントレジストリを依存関数から取得して判定する、テナントコンテキストの yield 依存関数を生成する。

    :func:`create_tenant_context_dependency` に ``RegistryTenantResolver(registry)`` を渡すのと同じ判定・
    同じエラーレスポンス（403 + コード文字列）になる。違いはレジストリを ``Depends(registry_dependency)``
    でリクエスト時に取得する点で、次の利点がある。

    - レジストリ（DB エンジン）の生成を最初のリクエストまで遅延できる（import 時に環境変数を読まない）。
    - テストで ``app.dependency_overrides[registry_dependency]`` によりフェイクに差し替えられる。
      レジストリを直接 ``Depends`` する他のエンドポイント（ログイン時の tenant_code 解決など）と
      同じ差し替えが効く。

    Args:
        registry_dependency: :class:`~modules.tenancy.registry.TenantRegistry` を返す依存関数。
            通常は :func:`modules.tenancy.providers.get_tenant_registry`。
        user_dependency: 認証済みユーザー情報（dict）を返す依存関数。未認証時の 401 はこちらが返す。

    Returns:
        TenantContextDependency: ``Depends`` に渡す async の yield 依存関数。
    """

    async def registry_tenant_context_dependency(user: Annotated[Mapping[str, Any], Depends(user_dependency)], registry: Annotated[TenantRegistry, Depends(registry_dependency)]) -> AsyncIterator[TenantContext]:
        """認証済みユーザーのテナントコンテキストをレジストリで判定し、リクエスト中だけ設定する。

        Raises:
            HTTPException(403): リゾルバが拒否した場合。``detail`` は失敗理由のコード文字列。
        """
        ctx = await _resolve_or_403(RegistryTenantResolver(registry), user)
        with tenant_scope(ctx):
            yield ctx

    return registry_tenant_context_dependency


async def _resolve_or_403(resolver: TenantResolver, user: Mapping[str, Any]) -> TenantContext:
    """リゾルバをスレッドプールで呼び、拒否された場合は 403 に変換する。

    Args:
        resolver: テナントコンテキストを導出する関数（ブロッキング I/O を含みうる）。
        user: 認証済みユーザー情報。

    Returns:
        TenantContext: 導出したテナントコンテキスト。

    Raises:
        HTTPException(403): :class:`~modules.tenancy.resolver.TenantResolutionError` の場合。
            ``detail`` は失敗理由のコード文字列（例: ``tenant_inactive``）。
    """
    try:
        return await run_in_threadpool(resolver, user)
    except TenantResolutionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.code.value) from exc
