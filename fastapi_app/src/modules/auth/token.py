#!/usr/bin/env python
# coding:utf-8
"""OIDC の PKCE 生成と id_token 検証を担うモジュール。

提供する機能:
    - :func:`generate_pkce_pair` — PKCE の ``code_verifier`` / ``code_challenge`` を生成する。
    - :func:`generate_nonce` — id_token のリプレイ検知に使う nonce を生成する。
    - :func:`verify_id_token` — KeyCloak の JWKS で id_token の署名とクレームを検証する。
    - :func:`build_token_record` — トークンレスポンスを絶対時刻の有効期限付きに正規化する。
    - :func:`refresh_access_token` — refresh token で access token を更新する。

設計方針:
    署名検証に使う公開鍵は KeyCloak の JWKS エンドポイントから取得する。
    JWKS の取得はサーバー間通信のためコンテナ内部 URL を使用し、
    ``PyJWKClient`` のインスタンスを JWKS URI 単位でキャッシュして
    リクエストのたびに取得しにいかないようにする。
"""
import hashlib
import secrets
import time
from base64 import urlsafe_b64encode
from functools import lru_cache
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

# PKCE で使用するチャレンジ方式。平文の ``plain`` は使用しない。
CODE_CHALLENGE_METHOD = "S256"

# 許可する署名アルゴリズム。KeyCloak の既定は RS256。
ALLOWED_ALGORITHMS = ["RS256"]

# access token の有効期限がこの秒数以内に迫っていれば、事前に更新する。
# 検証中に期限切れになることを避けるための猶予。
TOKEN_REFRESH_LEEWAY_SECONDS = 30


def _base64url_encode(data: bytes) -> str:
    """バイト列をパディングなしの Base64URL 文字列に変換する。

    Args:
        data: 変換対象のバイト列。

    Returns:
        str: パディング(``=``)を除去した Base64URL 文字列。
    """
    return urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce_pair() -> tuple[str, str]:
    """PKCE の ``code_verifier`` と ``code_challenge`` の組を生成する。

    ``code_verifier`` は認可リクエスト時にはサーバー側で保持し、
    トークン交換時にのみ KeyCloak へ送信する。これにより、認可コードを
    傍受されても ``code_verifier`` を持たない第三者はトークンを取得できない。

    Returns:
        tuple[str, str]: ``(code_verifier, code_challenge)`` の組。
                         ``code_challenge`` は S256 方式で算出される。
    """
    code_verifier = _base64url_encode(secrets.token_bytes(32))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = _base64url_encode(digest)
    return code_verifier, code_challenge


def generate_nonce() -> str:
    """id_token に埋め込む nonce を生成する。

    認可リクエスト時に送信した値と id_token の ``nonce`` クレームが
    一致することを検証することで、トークンのリプレイを検知できる。

    Returns:
        str: URL-safe なランダム文字列。
    """
    return secrets.token_urlsafe(24)


@lru_cache(maxsize=16)
def _jwks_client(jwks_uri: str) -> PyJWKClient:
    """JWKS URI ごとに ``PyJWKClient`` を生成してキャッシュする。

    Args:
        jwks_uri: KeyCloak の JWKS エンドポイント URL。

    Returns:
        PyJWKClient: 署名鍵の取得に使用するクライアント。
    """
    return PyJWKClient(jwks_uri, cache_keys=True)


def verify_id_token(
    id_token: str,
    jwks_uri: str,
    audience: str,
    allowed_issuers: list[str],
    expected_nonce: str | None = None,
) -> dict[str, Any]:
    """id_token の署名とクレームを検証し、payload を返す。

    検証内容:
        - JWKS から取得した公開鍵による **署名検証** (RS256)
        - ``exp`` / ``iat`` の有効期限
        - ``aud`` がクライアント ID と一致すること
        - ``iss`` が許容 issuer のいずれかと一致すること
        - ``nonce`` が認可リクエスト時の値と一致すること (指定時のみ)

    Note:
        ``iss`` は PyJWT に任せず自前で検証している。本構成では
        KeyCloak の内部 URL と外部公開 URL のどちらが issuer になるかが
        ホスト名設定に依存するため、複数の候補を許容する必要があるため。

    Args:
        id_token: KeyCloak のトークンエンドポイントから受け取った id_token。
        jwks_uri: 署名鍵を取得する JWKS エンドポイント URL。
        audience: 期待する ``aud`` クレーム (OIDC クライアント ID)。
        allowed_issuers: 許容する ``iss`` クレームのリスト。
        expected_nonce: 認可リクエスト時に送信した nonce。``None`` の場合は検証しない。

    Returns:
        dict: 検証済みの id_token payload。

    Raises:
        jwt.PyJWTError: 署名不正、期限切れ、``aud`` 不一致など JWT の検証に失敗した場合。
        ValueError: ``iss`` または ``nonce`` が期待値と一致しない場合。
    """
    signing_key = _jwks_client(jwks_uri).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=ALLOWED_ALGORITHMS,
        audience=audience,
        options={
            # iss は許容値が複数あるため、下で自前検証する
            "verify_iss": False,
            "require": ["exp", "iat", "iss", "aud", "sub"],
        },
    )

    issuer = claims.get("iss")
    if issuer not in allowed_issuers:
        raise ValueError(f"Unexpected issuer: {issuer}")

    if expected_nonce is not None and claims.get("nonce") != expected_nonce:
        raise ValueError("Nonce mismatch")

    return claims


def verify_access_token(access_token: str, jwks_uri: str, authorized_party: str, allowed_issuers: list[str]) -> dict[str, Any]:
    """access token の署名とクレームを検証し、payload を返す。

    ロール (``realm_access.roles``) は Keycloak の既定では access token にだけ載るため、
    ログイン完了時にこれを検証してから読み取る。

    検証内容:
        - JWKS から取得した公開鍵による **署名検証** (RS256)
        - ``exp`` / ``iat`` の有効期限
        - ``iss`` が許容 issuer のいずれかと一致すること
        - ``azp`` (authorized party) がクライアント ID と一致すること

    Note:
        ``aud`` は検証しない。Keycloak の access token の ``aud`` は Audience マッパーの有無で
        変わる (未設定のレルムでは ``account`` 等になる) ため、発行先クライアントの確認は
        ``azp`` で行う (01 §7.4「audience / authorized party」)。

    Args:
        access_token: トークンエンドポイントから受け取った access token。
        jwks_uri: 署名鍵を取得する JWKS エンドポイント URL。
        authorized_party: 期待する ``azp`` (OIDC クライアント ID)。
        allowed_issuers: 許容する ``iss`` クレームのリスト。

    Returns:
        dict: 検証済みの access token payload。

    Raises:
        jwt.PyJWTError: 署名不正、期限切れなど JWT の検証に失敗した場合。
        ValueError: ``iss`` または ``azp`` が期待値と一致しない場合。
    """
    signing_key = _jwks_client(jwks_uri).get_signing_key_from_jwt(access_token)
    claims = jwt.decode(
        access_token,
        signing_key.key,
        algorithms=ALLOWED_ALGORITHMS,
        options={
            "verify_aud": False,
            "verify_iss": False,
            "require": ["exp", "iat", "iss"],
        },
    )

    issuer = claims.get("iss")
    if issuer not in allowed_issuers:
        raise ValueError(f"Unexpected issuer: {issuer}")
    if claims.get("azp") != authorized_party:
        raise ValueError("Unexpected authorized party")
    return claims


def extract_realm_roles(claims: dict[str, Any]) -> list[str]:
    """access token の ``realm_access.roles`` を取り出す。

    Args:
        claims: access token の payload。

    Returns:
        list[str]: レルムロール。無い場合は空リスト。
    """
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
    return [role for role in roles if isinstance(role, str)] if isinstance(roles, list) else []


def build_token_record(token_data: dict[str, Any]) -> dict[str, Any]:
    """KeyCloak のトークンレスポンスをセッション保存用に正規化する。

    ``expires_in`` は「取得時点からの秒数」であり、そのまま保存しても後から
    期限切れかどうかを判定できない。取得時刻を加えた**絶対時刻**に変換して保持する。

    Args:
        token_data: トークンエンドポイントのレスポンス dict。

    Returns:
        dict: ``access_token`` / ``refresh_token`` / ``id_token`` と、
              ``access_token_expires_at`` / ``refresh_token_expires_at``
              (UNIX 時刻) を持つ dict。
    """
    now = time.time()
    return {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        # RP-Initiated Logout の id_token_hint に使用するため保持する
        "id_token": token_data.get("id_token"),
        "access_token_expires_at": now + float(token_data.get("expires_in") or 0),
        "refresh_token_expires_at": now + float(token_data.get("refresh_expires_in") or 0),
    }


def is_access_token_expired(tokens: dict[str, Any], leeway_seconds: int = TOKEN_REFRESH_LEEWAY_SECONDS) -> bool:
    """access token が期限切れ (または期限が迫っている) かを判定する。

    Args:
        tokens: :func:`build_token_record` が生成したトークン情報。
        leeway_seconds: 期限切れとみなす猶予秒数。

    Returns:
        bool: 更新が必要な場合は ``True``。
    """
    expires_at = tokens.get("access_token_expires_at")
    if not expires_at:
        # 期限情報が無い場合は安全側に倒して更新させる
        return True
    return time.time() >= float(expires_at) - leeway_seconds


def is_refresh_token_expired(tokens: dict[str, Any]) -> bool:
    """refresh token が期限切れかを判定する。

    Args:
        tokens: :func:`build_token_record` が生成したトークン情報。

    Returns:
        bool: 期限切れの場合は ``True``。更新不能でありセッションを破棄すべき状態。
    """
    expires_at = tokens.get("refresh_token_expires_at")
    if not expires_at:
        return False
    return time.time() >= float(expires_at)


def refresh_access_token(token_url: str, client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any] | None:
    """refresh token を使って access token を更新する。

    KeyCloak は更新時に refresh token も再発行する (ローテーション) ため、
    戻り値の ``refresh_token`` で必ず保存し直すこと。

    Note:
        KeyCloak はトークンの ``iss`` とアクセス先 URL の一致を検証する。
        本構成では ``KC_HOSTNAME`` で issuer を固定しているため、
        コンテナ内部 URL からの呼び出しでも成功する。固定されていないと
        ``invalid_grant: Invalid token issuer`` で失敗する。

    Args:
        token_url: KeyCloak のトークンエンドポイント URL。
        client_id: OIDC クライアント ID。
        client_secret: OIDC クライアントシークレット。
        refresh_token: 現在の refresh token。

    Returns:
        dict | None: 更新に成功した場合は :func:`build_token_record` の戻り値。
                     失敗した場合は ``None`` (呼び出し側でセッションを破棄すること)。
    """
    try:
        response = httpx.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            timeout=10.0,
        )
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None
    return build_token_record(response.json())
