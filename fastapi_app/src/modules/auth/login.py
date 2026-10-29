"""ログイン完了時のトークン検証とセッション内容の組み立て。

通常のコールバック (``GET /api/auth/callback``) と開発用ログイン (``GET /api/auth/dev-login``) の
両方が使い、**同一内容のセッション** を作る。

セッションの内容::

    {
        "plane": "app" | "cp",
        "realm": "<レルム名>",
        "tenant_id": "<UUID>",          # AP のみ
        "tenant_code": "<tenant_code>", # AP のみ
        "tokens": {...},                # modules.auth.token.build_token_record の戻り値
        "user": {
            "sub", "preferred_username", "name", "given_name", "family_name", "email", "realm",
            "plane": "app" | "cp",
            "roles": [...],             # プレーンの許可リストにあるレルムロールのみ
            "tenant_id": "<UUID>",      # AP のみ (トークンの tenant_id クレーム)
        },
    }

検証内容 (01 §7.4):
    - id_token: 署名・``exp``・``aud`` (クライアント ID)・``iss``・``nonce``
    - access token: 署名・``exp``・``iss``・``azp`` (クライアント ID)。ロールを読むために使う
    - AP: トークンの ``tenant_id`` クレームが、レジストリ上の発行元レルムの ``tenant_id`` と一致すること
      (``expected_tenant_id`` を渡した場合。レジストリの ACTIVE 判定は呼び出し側で行う)
    - CP: 発行元が ``control-plane`` であり、``saas_admin`` または ``saas_viewer`` を持つこと
"""
import logging
import uuid
from typing import Any

from fastapi import HTTPException

from .environment import KeyCloakEnvironmentVariables
from .plane import CP_REALM_NAME, Plane, filter_roles
from .token import build_token_record, extract_realm_roles, verify_access_token, verify_id_token

logger = logging.getLogger(__name__)

# ログインを拒否したときの detail。理由 (テナント不一致・ロール不足など) を区別して返さない。
LOGIN_REJECTED_DETAIL = "Login rejected"


def _same_tenant_id(claimed: Any, expected: str) -> bool:
    """クレームの tenant_id と期待値が同じ UUID かどうかを返す (表記揺れを吸収する)。

    Args:
        claimed: トークンの ``tenant_id`` クレーム。
        expected: レジストリ上の tenant_id。

    Returns:
        bool: 一致する場合は ``True``。
    """
    if not isinstance(claimed, str) or not claimed:
        return False
    try:
        return uuid.UUID(claimed) == uuid.UUID(expected)
    except ValueError:
        return False


def build_login_session(
    config: KeyCloakEnvironmentVariables,
    plane: Plane,
    realm: str,
    token_data: dict[str, Any],
    *,
    expected_nonce: str | None,
    tenant_code: str | None = None,
    expected_tenant_id: str | None = None,
) -> dict[str, Any]:
    """トークンレスポンスを検証し、セッションに保存する内容を組み立てる。

    Args:
        config: KeyCloak 設定。
        plane: ログイン先のプレーン。
        realm: トークンの発行元レルム (state またはプロファイルから得た、サーバー側で決めた値)。
        token_data: トークンエンドポイントのレスポンス。
        expected_nonce: 認可リクエスト時の nonce。パスワードグラント (開発用ログイン) では ``None``。
        tenant_code: AP のテナントコード。
        expected_tenant_id: AP でトークンの ``tenant_id`` クレームと一致すべき値 (レジストリ上の値)。
            ``None`` の場合は一致を確認しない (開発用ログインのみ)。

    Returns:
        dict: セッションデータ。

    Raises:
        HTTPException(401): トークンが欠けている、または検証に失敗した場合。
        HTTPException(403): テナントの不一致、CP のロール不足、CP 以外のレルムでの CP ログインの場合。
    """
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    id_token = token_data.get("id_token")
    if not access_token or not refresh_token or not id_token:
        raise HTTPException(status_code=401, detail="Invalid token response")

    if plane == Plane.CP and realm != CP_REALM_NAME:
        raise HTTPException(status_code=403, detail=LOGIN_REJECTED_DETAIL)

    client_id = config.client_id_for(plane)
    allowed_issuers = config.allowed_issuers(realm)
    jwks_uri = config.build_jwks_uri(realm)
    try:
        id_claims = verify_id_token(id_token, jwks_uri=jwks_uri, audience=client_id, allowed_issuers=allowed_issuers, expected_nonce=expected_nonce)
        access_claims = verify_access_token(access_token, jwks_uri=jwks_uri, authorized_party=client_id, allowed_issuers=allowed_issuers)
    except Exception as exc:
        # 検証失敗は認証失敗として扱う。例外メッセージにトークンは含まれない。
        logger.warning("token verification failed (plane=%s realm=%s): %s", plane.value, realm, exc)
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    if id_claims.get("sub") != access_claims.get("sub") and access_claims.get("sub") is not None:
        logger.warning("token subject mismatch (plane=%s realm=%s)", plane.value, realm)
        raise HTTPException(status_code=401, detail="Invalid token")

    roles = filter_roles(plane, extract_realm_roles(access_claims))
    user: dict[str, Any] = {
        "sub": id_claims.get("sub"),
        "preferred_username": id_claims.get("preferred_username"),
        # 表示名 (姓・名から作られる)。AP のログイン時のユーザー同期に使う (main_app.route.auth.login_sync)
        "name": id_claims.get("name"),
        # 名・姓。AP のログイン時のユーザー同期で一覧表示用の写し (t_user.first_name / last_name) を更新する
        "given_name": id_claims.get("given_name"),
        "family_name": id_claims.get("family_name"),
        "email": id_claims.get("email"),
        "realm": realm,
        "plane": plane.value,
        "roles": roles,
    }
    session: dict[str, Any] = {"plane": plane.value, "realm": realm}

    if plane == Plane.CP:
        if not roles:
            logger.warning("cp login rejected: no cp role (realm=%s)", realm)
            raise HTTPException(status_code=403, detail=LOGIN_REJECTED_DETAIL)
    else:
        claimed_tenant_id = id_claims.get("tenant_id") or access_claims.get("tenant_id")
        if expected_tenant_id is not None and not _same_tenant_id(claimed_tenant_id, expected_tenant_id):
            logger.warning("app login rejected: tenant_id claim does not match the registry (realm=%s)", realm)
            raise HTTPException(status_code=403, detail=LOGIN_REJECTED_DETAIL)
        tenant_id = expected_tenant_id or (claimed_tenant_id if isinstance(claimed_tenant_id, str) and claimed_tenant_id else None)
        if tenant_id is not None:
            user["tenant_id"] = tenant_id
            session["tenant_id"] = tenant_id
        session["tenant_code"] = tenant_code

    session["tokens"] = build_token_record(token_data)
    session["user"] = user
    return session
