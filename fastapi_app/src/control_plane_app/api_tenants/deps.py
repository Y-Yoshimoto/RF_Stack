#!/usr/bin/env python
# coding:utf-8
"""テナント管理 API の依存関数。"""
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends

from control_plane_app.services.tenant_provisioning import TenantProvisioningService
from modules.auth.dependency import require_cp_roles
from modules.keycloak_admin.templates import create_provisioner_admin_client
from modules.tenancy.providers import CpSessionDep

# 変更系の操作を許可する CP ユーザー（saas_admin のみ。01 §7.5）。
require_saas_admin = require_cp_roles("saas_admin")
CpAdminDep = Annotated[dict[str, Any], Depends(require_saas_admin)]


def get_provisioning_service(session: CpSessionDep) -> Iterator[TenantProvisioningService]:
    """払い出しサービスを 1 リクエスト分だけ作って yield する FastAPI 依存関数。

    Keycloak の管理クライアントは締め切り（30 秒）が作成時点から数えるため、リクエストごとに作り、
    リクエストの終わりに閉じる（CP-ONB-06）。``saas_admin`` の確認（:data:`require_saas_admin`）より後に解決されるよう、
    変更系のエンドポイントはデコレーターの ``dependencies`` に :data:`require_saas_admin` を指定する
    （デコレーターの依存関数は引数の依存関数より先に解決される）。テストでは ``app.dependency_overrides`` で差し替える。

    Args:
        session: CP DB のセッション。

    Yields:
        TenantProvisioningService: 払い出しサービス。
    """
    with create_provisioner_admin_client() as admin:
        yield TenantProvisioningService(session, admin)


ProvisioningServiceDep = Annotated[TenantProvisioningService, Depends(get_provisioning_service)]
