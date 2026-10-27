"""Keycloak Admin 操作の入力仕様 (Spec) と戻り値 (Result) の型定義。

Spec は「あるべき状態」を表し、``to_representation()`` で Keycloak の Representation (JSON) に変換する。
Result は ensure 系関数の戻り値で、作成したかどうか (``created``) を含む。
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# クライアント属性 ``post.logout.redirect.uris`` で複数値を連結する区切り文字 (Keycloak の仕様)。
POST_LOGOUT_REDIRECT_URIS_SEPARATOR = "##"


@dataclass(frozen=True, kw_only=True)
class RealmSpec:
    """レルムのあるべき状態。

    Attributes:
        realm: レルム名。
        enabled: 有効にするか。
        settings: 追加のレルム設定 (例: ``{"duplicateEmailsAllowed": False, "bruteForceProtected": True}``)。
                  指定した場合、既存レルムにも反映 (部分更新) する。
    """

    realm: str
    enabled: bool = True
    settings: Mapping[str, Any] = field(default_factory=dict)

    def to_representation(self) -> dict[str, Any]:
        """RealmRepresentation に変換する。

        Returns:
            dict[str, Any]: Keycloak に送る JSON。
        """
        return {**self.settings, "realm": self.realm, "enabled": self.enabled}


@dataclass(frozen=True, kw_only=True)
class RealmResult:
    """``ensure_realm`` の結果。

    Attributes:
        realm: レルム名。
        created: 今回作成したか。
        updated: 既存レルムの設定を更新したか。
    """

    realm: str
    created: bool
    updated: bool = False


@dataclass(frozen=True, kw_only=True)
class ClientSpec:
    """OIDC クライアントのあるべき状態。

    既定値は旧シェルスクリプトが作成していた BFF 用の confidential クライアントに合わせている。

    Attributes:
        client_id: クライアント ID。
        redirect_uris: Valid redirect URIs。
        web_origins: Web origins。
        post_logout_redirect_uris: Valid post logout redirect URIs。
        public_client: public クライアントにするか (``False`` = confidential)。
        standard_flow_enabled: 認可コードフローを有効にするか。
        direct_access_grants_enabled: パスワードグラントを有効にするか (開発用ログインバイパスで使用)。
        service_accounts_enabled: サービスアカウント (クライアントクレデンシャル) を有効にするか。
        attributes: 追加のクライアント属性。
        extra: その他の ClientRepresentation フィールド。
    """

    client_id: str
    redirect_uris: tuple[str, ...] = ()
    web_origins: tuple[str, ...] = ()
    post_logout_redirect_uris: tuple[str, ...] = ()
    enabled: bool = True
    public_client: bool = False
    standard_flow_enabled: bool = True
    direct_access_grants_enabled: bool = True
    service_accounts_enabled: bool = False
    attributes: Mapping[str, str] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_representation(self) -> dict[str, Any]:
        """ClientRepresentation に変換する。

        Returns:
            dict[str, Any]: Keycloak に送る JSON。
        """
        attributes = dict(self.attributes)
        if self.post_logout_redirect_uris:
            attributes["post.logout.redirect.uris"] = POST_LOGOUT_REDIRECT_URIS_SEPARATOR.join(self.post_logout_redirect_uris)
        return {
            **self.extra,
            "clientId": self.client_id,
            "enabled": self.enabled,
            "protocol": "openid-connect",
            "publicClient": self.public_client,
            "standardFlowEnabled": self.standard_flow_enabled,
            "directAccessGrantsEnabled": self.direct_access_grants_enabled,
            "serviceAccountsEnabled": self.service_accounts_enabled,
            "redirectUris": list(self.redirect_uris),
            "webOrigins": list(self.web_origins),
            "attributes": attributes,
        }


@dataclass(frozen=True, kw_only=True)
class ClientResult:
    """``ensure_client`` の結果。

    Attributes:
        id: クライアントの内部 ID (UUID)。Admin API のパスで使う。
        client_id: クライアント ID。
        created: 今回作成したか。
        updated: 既存クライアントの設定を更新したか。
    """

    id: str
    client_id: str
    created: bool
    updated: bool = False


@dataclass(frozen=True, kw_only=True)
class UserSpec:
    """ユーザーのあるべき状態 (作成時に使用する)。

    既存ユーザーは更新しない (旧シェルスクリプトと同じ)。

    Attributes:
        username: ユーザー名。Keycloak は小文字に正規化する。
        enabled: 有効にするか。
        email: メールアドレス。
        email_verified: メール確認済みにするか。
        first_name: 名。
        last_name: 姓。
        required_actions: 必須アクション (例: ``("UPDATE_PASSWORD",)``)。
        attributes: ユーザー属性。
    """

    username: str
    enabled: bool = True
    email: str | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None
    required_actions: tuple[str, ...] = ()
    attributes: Mapping[str, list[str]] = field(default_factory=dict)

    def to_representation(self) -> dict[str, Any]:
        """UserRepresentation に変換する。

        Returns:
            dict[str, Any]: Keycloak に送る JSON。
        """
        representation: dict[str, Any] = {"username": self.username, "enabled": self.enabled, "emailVerified": self.email_verified}
        if self.email is not None:
            representation["email"] = self.email
        if self.first_name is not None:
            representation["firstName"] = self.first_name
        if self.last_name is not None:
            representation["lastName"] = self.last_name
        if self.required_actions:
            representation["requiredActions"] = list(self.required_actions)
        if self.attributes:
            representation["attributes"] = {key: list(values) for key, values in self.attributes.items()}
        return representation


@dataclass(frozen=True, kw_only=True)
class UserResult:
    """``ensure_user`` の結果。

    Attributes:
        id: ユーザーの内部 ID (UUID)。
        username: ユーザー名。
        created: 今回作成したか。
    """

    id: str
    username: str
    created: bool


@dataclass(frozen=True, kw_only=True)
class RoleResult:
    """``ensure_realm_role`` の結果。

    Attributes:
        id: ロールの内部 ID。
        name: ロール名。
        created: 今回作成したか。
    """

    id: str
    name: str
    created: bool


@dataclass(frozen=True, kw_only=True)
class ProtocolMapperSpec:
    """クライアントのプロトコルマッパーのあるべき状態。

    マッパーはクライアント内で ``name`` により同定する。

    Attributes:
        name: マッパー名。
        protocol_mapper: マッパー種別 (例: ``oidc-hardcoded-claim-mapper``)。
        config: マッパー設定。値はすべて文字列 (Keycloak の仕様)。
        protocol: プロトコル。
    """

    name: str
    protocol_mapper: str
    config: Mapping[str, str] = field(default_factory=dict)
    protocol: str = "openid-connect"

    def to_representation(self) -> dict[str, Any]:
        """ProtocolMapperRepresentation に変換する。

        Returns:
            dict[str, Any]: Keycloak に送る JSON。
        """
        return {"name": self.name, "protocol": self.protocol, "protocolMapper": self.protocol_mapper, "config": dict(self.config)}


@dataclass(frozen=True, kw_only=True)
class ProtocolMapperResult:
    """``ensure_protocol_mapper`` の結果。

    Attributes:
        id: マッパーの内部 ID。
        name: マッパー名。
        created: 今回作成したか。
        updated: 既存マッパーの設定を更新したか。
    """

    id: str
    name: str
    created: bool
    updated: bool = False


@dataclass(frozen=True, kw_only=True)
class SetupResult:
    """``setup_realm_client_user`` (旧シェルスクリプト相当) の結果。

    Attributes:
        realm: レルムの結果。
        client: クライアントの結果。
        client_secret: クライアントシークレット。``repr`` には出さない。
        user: ユーザーの結果。
    """

    realm: RealmResult
    client: ClientResult
    client_secret: str = field(repr=False)
    user: UserResult
