"""OIDC クライアント・クライアントシークレット・プロトコルマッパーの冪等な操作。"""
import logging
from collections.abc import Mapping
from typing import Any

from .admin_client import KeycloakAdminClient, created_id_from_location
from .errors import KeycloakAdminError
from .models import ClientResult, ClientSpec, ProtocolMapperResult, ProtocolMapperSpec

logger = logging.getLogger(__name__)


def find_client(admin: KeycloakAdminClient, realm: str, client_id: str) -> dict | None:
    """クライアント ID でクライアントを検索する。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_id: クライアント ID (``clientId``。内部 ID ではない)。

    Returns:
        dict | None: ClientRepresentation。存在しない場合は ``None``。
    """
    clients = admin.get_json(admin.realm_url(realm, "clients"), operation=f"query clients in realm {realm}", params={"clientId": client_id})
    # clientId 検索は既定で完全一致だが、念のため結果側でも照合する。
    return next((client for client in clients or [] if client.get("clientId") == client_id), None)


def _require_client(admin: KeycloakAdminClient, realm: str, client_id: str) -> dict:
    """クライアントを検索し、見つからなければ例外にする。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_id: クライアント ID。

    Returns:
        dict: ClientRepresentation。

    Raises:
        KeycloakAdminError: 見つからない場合。
    """
    client = find_client(admin, realm, client_id)
    if client is None or not client.get("id"):
        raise KeycloakAdminError(f"resolve client internal id for {client_id} in realm {realm}")
    return client


def ensure_client(admin: KeycloakAdminClient, realm: str, spec: ClientSpec, *, update_existing: bool = True) -> ClientResult:
    """クライアントが存在し、``spec`` の設定になっていることを保証する。

    既存クライアントは ``update_existing`` が真なら毎回 PUT で設定を反映する。
    「already exists」でスキップすると古い設定 (``directAccessGrantsEnabled`` など) が残るため。
    PUT は部分更新であり、``spec`` に含まれないフィールド (シークレット等) は変わらない。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        spec: クライアントのあるべき状態。
        update_existing: 既存クライアントの設定を更新するか。

    Returns:
        ClientResult: 結果。

    Raises:
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    representation = spec.to_representation()
    existing = find_client(admin, realm, spec.client_id)

    if existing is None:
        response = admin.request(
            "POST", admin.realm_url(realm, "clients"), operation=f"create client {spec.client_id} in realm {realm}", expected=(201, 409), json=representation
        )
        if response.status_code == 201:
            internal_id = created_id_from_location(response) or _require_client(admin, realm, spec.client_id)["id"]
            logger.info("クライアントを作成しました: realm=%s client_id=%s", realm, spec.client_id)
            return ClientResult(id=internal_id, client_id=spec.client_id, created=True)
        # 409: 並行実行などで先に作成された。既存として扱う。
        existing = _require_client(admin, realm, spec.client_id)

    internal_id = existing["id"]
    logger.info("クライアントは既に存在します: realm=%s client_id=%s", realm, spec.client_id)
    if not update_existing:
        return ClientResult(id=internal_id, client_id=spec.client_id, created=False)

    admin.request("PUT", admin.realm_url(realm, "clients", internal_id), operation=f"update client {spec.client_id} in realm {realm}", expected=(204,), json=representation)
    logger.info("クライアントの設定を更新しました: realm=%s client_id=%s", realm, spec.client_id)
    return ClientResult(id=internal_id, client_id=spec.client_id, created=False, updated=True)


def get_client_secret(admin: KeycloakAdminClient, realm: str, client_internal_id: str) -> str:
    """confidential クライアントの現在のシークレットを取得する (再発行はしない)。

    戻り値は秘匿値のため、ログや例外メッセージに含めないこと。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_internal_id: クライアントの内部 ID (``ClientResult.id``)。

    Returns:
        str: クライアントシークレット。

    Raises:
        KeycloakAdminError: 取得に失敗した、またはシークレットが空 (public クライアント等) の場合。
    """
    operation = f"fetch client secret in realm {realm}"
    body = admin.get_json(admin.realm_url(realm, "clients", client_internal_id, "client-secret"), operation=operation)
    value = body.get("value") if isinstance(body, dict) else None
    if not value:
        raise KeycloakAdminError(operation, detail="client secret is empty (is the client confidential?)")
    return value


def list_protocol_mappers(admin: KeycloakAdminClient, realm: str, client_internal_id: str) -> list[dict]:
    """クライアントのプロトコルマッパー一覧を取得する。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_internal_id: クライアントの内部 ID。

    Returns:
        list[dict]: ProtocolMapperRepresentation のリスト。
    """
    url = admin.realm_url(realm, "clients", client_internal_id, "protocol-mappers", "models")
    return admin.get_json(url, operation=f"query protocol mappers in realm {realm}") or []


def _find_protocol_mapper(admin: KeycloakAdminClient, realm: str, client_internal_id: str, name: str) -> dict | None:
    """名前でプロトコルマッパーを検索する。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_internal_id: クライアントの内部 ID。
        name: マッパー名。

    Returns:
        dict | None: ProtocolMapperRepresentation。存在しない場合は ``None``。
    """
    return next((mapper for mapper in list_protocol_mappers(admin, realm, client_internal_id) if mapper.get("name") == name), None)


def _require_protocol_mapper(admin: KeycloakAdminClient, realm: str, client_internal_id: str, name: str) -> dict:
    """名前でプロトコルマッパーを検索し、見つからなければ例外にする。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_internal_id: クライアントの内部 ID。
        name: マッパー名。

    Returns:
        dict: ProtocolMapperRepresentation。

    Raises:
        KeycloakAdminError: 見つからない場合。
    """
    mapper = _find_protocol_mapper(admin, realm, client_internal_id, name)
    if mapper is None or not mapper.get("id"):
        raise KeycloakAdminError(f"resolve protocol mapper id for {name} in realm {realm}")
    return mapper


def _mapper_matches(existing: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    """既存マッパーがあるべき状態と一致するかを判定する。

    Args:
        existing: 既存の ProtocolMapperRepresentation。
        desired: あるべき ProtocolMapperRepresentation。

    Returns:
        bool: 種別・プロトコル・指定した config がすべて一致する場合に ``True``。
    """
    if existing.get("protocolMapper") != desired["protocolMapper"] or existing.get("protocol") != desired["protocol"]:
        return False
    existing_config = existing.get("config") or {}
    return all(existing_config.get(key) == value for key, value in desired["config"].items())


def ensure_protocol_mapper(admin: KeycloakAdminClient, realm: str, client_internal_id: str, spec: ProtocolMapperSpec) -> ProtocolMapperResult:
    """クライアントにプロトコルマッパーが ``spec`` の設定で存在することを保証する。

    マッパーは ``name`` で同定する。既存マッパーの設定が異なる場合のみ PUT で更新する。
    作成時に 409 (並行実行などで先に作成された) が返った場合は、他の ensure 系と同様に既存として扱う。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_internal_id: クライアントの内部 ID。
        spec: マッパーのあるべき状態。

    Returns:
        ProtocolMapperResult: 結果。

    Raises:
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    desired = spec.to_representation()
    existing = _find_protocol_mapper(admin, realm, client_internal_id, spec.name)

    if existing is None:
        url = admin.realm_url(realm, "clients", client_internal_id, "protocol-mappers", "models")
        response = admin.request("POST", url, operation=f"create protocol mapper {spec.name} in realm {realm}", expected=(201, 409), json=desired)
        if response.status_code == 201:
            mapper_id = created_id_from_location(response) or _require_protocol_mapper(admin, realm, client_internal_id, spec.name)["id"]
            logger.info("プロトコルマッパーを作成しました: realm=%s name=%s", realm, spec.name)
            return ProtocolMapperResult(id=mapper_id, name=spec.name, created=True)
        # 409: 並行実行などで先に作成された。既存として扱い、以降の差分判定に進む。
        existing = _require_protocol_mapper(admin, realm, client_internal_id, spec.name)

    mapper_id = existing["id"]
    if _mapper_matches(existing, desired):
        return ProtocolMapperResult(id=mapper_id, name=spec.name, created=False)

    url = admin.realm_url(realm, "clients", client_internal_id, "protocol-mappers", "models", mapper_id)
    admin.request("PUT", url, operation=f"update protocol mapper {spec.name} in realm {realm}", expected=(204,), json={**desired, "id": mapper_id})
    logger.info("プロトコルマッパーの設定を更新しました: realm=%s name=%s", realm, spec.name)
    return ProtocolMapperResult(id=mapper_id, name=spec.name, created=False, updated=True)


def _token_flags(*, id_token: bool, access_token: bool, userinfo: bool, introspection: bool) -> dict[str, str]:
    """マッパー config のトークン出力フラグを組み立てる。

    Args:
        id_token: id_token に含めるか。
        access_token: access_token に含めるか。
        userinfo: userinfo に含めるか。
        introspection: introspection 結果に含めるか。

    Returns:
        dict[str, str]: config の一部。
    """
    return {
        "id.token.claim": str(id_token).lower(),
        "access.token.claim": str(access_token).lower(),
        "userinfo.token.claim": str(userinfo).lower(),
        "introspection.token.claim": str(introspection).lower(),
    }


def hardcoded_claim_mapper(name: str, claim_name: str, claim_value: str, *, json_type: str = "String", id_token: bool = True, access_token: bool = True, userinfo: bool = True) -> ProtocolMapperSpec:
    """固定値クレームを付与するマッパー (``oidc-hardcoded-claim-mapper``) の仕様を作る。

    テナントテンプレートでの ``tenant_id`` クレーム付与を想定している。

    Args:
        name: マッパー名。
        claim_name: クレーム名 (例: ``tenant_id``)。
        claim_value: クレーム値。
        json_type: クレームの JSON 型。
        id_token: id_token に含めるか。
        access_token: access_token に含めるか。
        userinfo: userinfo に含めるか。

    Returns:
        ProtocolMapperSpec: マッパーの仕様。
    """
    config = {"claim.name": claim_name, "claim.value": claim_value, "jsonType.label": json_type}
    config.update(_token_flags(id_token=id_token, access_token=access_token, userinfo=userinfo, introspection=True))
    return ProtocolMapperSpec(name=name, protocol_mapper="oidc-hardcoded-claim-mapper", config=config)


def audience_mapper(name: str, included_client_audience: str, *, id_token: bool = False, access_token: bool = True) -> ProtocolMapperSpec:
    """``aud`` にクライアントを追加するマッパー (``oidc-audience-mapper``) の仕様を作る。

    Args:
        name: マッパー名。
        included_client_audience: ``aud`` に含めるクライアント ID。
        id_token: id_token に含めるか。
        access_token: access_token に含めるか。

    Returns:
        ProtocolMapperSpec: マッパーの仕様。
    """
    config = {
        "included.client.audience": included_client_audience,
        "id.token.claim": str(id_token).lower(),
        "access.token.claim": str(access_token).lower(),
        "introspection.token.claim": "true",
    }
    return ProtocolMapperSpec(name=name, protocol_mapper="oidc-audience-mapper", config=config)
