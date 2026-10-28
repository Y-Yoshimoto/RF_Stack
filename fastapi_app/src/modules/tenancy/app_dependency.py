#!/usr/bin/env python
# coding:utf-8
"""アプリケーションプレーン(AP)のルーターで使う、テナントコンテキストと DB セッションの依存関数。

AP の認証依存関数（:func:`modules.auth.dependency.get_current_app_user`）とテナントレジストリ
（:func:`modules.tenancy.providers.get_tenant_registry`）から組み立てる。

提供するもの:
    - :func:`get_app_tenant_context` / :data:`AppTenantContextDep` — セッションのユーザー情報を
      レジストリと照合し、リクエストの間だけテナントコンテキストを設定する async yield 依存関数。
      拒否時は 403（``detail`` は ``tenant_not_found`` / ``tenant_mismatch`` / ``tenant_inactive`` 等）。
    - :func:`get_app_db_session` / :data:`AppSessionDep` — テナントコンテキスト下で ``app_db``
      （``app_runtime``）の Session を yield する依存関数。:func:`get_app_tenant_context` に依存するため、
      引数の並び順やルーターへの適用有無に関わらず、必ずテナントの判定後にセッションが開始される。

使用例::

    from modules.tenancy.app_dependency import AppSessionDep, get_app_tenant_context

    router = APIRouter(dependencies=[Depends(get_app_tenant_context)])

    @router.get("/todos")
    def list_todos(session: AppSessionDep) -> list[TodoRead]:
        return todo_service.list_todos(session)  # テナントはコンテキストから得る

テストでの差し替え（``app.dependency_overrides``）:
    - ユーザー: ``get_current_app_user``
    - レジストリ: ``get_tenant_registry``（ログイン時の解決などと同じ差し替えが効く）
    - テナント判定ごと: ``get_app_tenant_context``（差し替える依存関数でも
      ``tenant_scope`` によりコンテキストを設定すること。設定しないと :func:`get_app_db_session` が
      ``TenantContextMissingError`` になる）

置き場所:
    02 §5.1 で ``main_app`` と ``control_plane_app`` の共有は ``modules`` のみとされ、AP の認証依存関数も
    ``modules/auth`` にあるため、AP 用の組み立てもテナント部品と同じ ``modules/tenancy`` に置く。
    ``modules/auth`` から :mod:`modules.tenancy.providers` を参照しても循環しないよう、
    認証への依存は本モジュールに分離している（``providers`` は ``modules.auth`` を import しない）。
"""
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from modules.auth.dependency import get_current_app_user

from .context import TenantContext
from .dependency import create_registry_tenant_context_dependency
from .providers import get_tenant_registry, open_app_session

# AP のテナントコンテキスト依存関数（async yield）。
get_app_tenant_context = create_registry_tenant_context_dependency(get_tenant_registry, user_dependency=get_current_app_user)

AppTenantContextDep = Annotated[TenantContext, Depends(get_app_tenant_context)]


def get_app_db_session(_tenant: AppTenantContextDep) -> Iterator[Session]:
    """テナントコンテキスト下で ``app_db``（``app_runtime``）の Session を yield する FastAPI 依存関数。

    :func:`get_app_tenant_context` に依存するため、テナントの判定（未認証 401 / 拒否 403）を通過した
    リクエストでのみセッションを開始する。同じリクエスト内では依存関数の結果がキャッシュされるため、
    ルーターにも :func:`get_app_tenant_context` を適用していても判定は 1 回で済む。

    トランザクション開始時に GUC ``app.current_tenant`` が自動設定される（RLS）。
    コミットはサービス層で行い、未コミットの変更はリクエスト終了時に破棄される。

    Args:
        _tenant: テナントコンテキスト（順序の保証のために受け取る。値はコンテキストから参照する）。

    Yields:
        Session: ``app_runtime`` のセッション。

    Raises:
        TenantContextMissingError: テナントコンテキストが設定されていない場合
            （``get_app_tenant_context`` をコンテキストを設定しない関数で差し替えた場合など）。
    """
    with open_app_session() as session:
        yield session


AppSessionDep = Annotated[Session, Depends(get_app_db_session)]
