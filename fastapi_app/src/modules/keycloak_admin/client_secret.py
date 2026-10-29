"""OIDC クライアントシークレットの導出 (docs/architecture/02-platform-implementation.md §3.3)。

クライアントシークレットは保存せず、基盤のシード値と「レルム名・クライアント ID」から決定的に導出する::

    secret = base64url_nopad( HMAC-SHA256( KC_CLIENT_SECRET_SEED, "{realm}:{client_id}" ) )

- 払い出し (CP) と CLI は、この値を Keycloak のクライアントに設定する。
- BFF (AP / CP) は同じ式で導出してトークンエンドポイントに提示する。DB には保存しない。
- ローテーションはシード値を変更し、全レルムでシークレットを設定し直す。

戻り値・シード値はいずれも秘匿値のため、ログや例外メッセージに含めないこと。
"""
import base64
import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

# シード値を与える環境変数名。
CLIENT_SECRET_SEED_ENV = "KC_CLIENT_SECRET_SEED"

# 開発用の既定シード値。APP_ENV=development 以外では使用を拒否する。
INSECURE_DEFAULT_CLIENT_SECRET_SEED = "change-me-client-secret-seed"


def derive_client_secret(seed: str, realm: str, client_id: str) -> str:
    """シード値・レルム名・クライアント ID からクライアントシークレットを導出する。

    Args:
        seed: シード値 (``KC_CLIENT_SECRET_SEED``)。空文字は不可。
        realm: レルム名。
        client_id: クライアント ID (``clientId``。内部 ID ではない)。

    Returns:
        str: パディングなし Base64URL の HMAC-SHA256 値 (43 文字)。

    Raises:
        ValueError: いずれかの引数が空の場合、またはレルム名・クライアント ID に区切り文字 ``:`` を含む場合
            (``"a:b" + ":" + "c"`` と ``"a" + ":" + "b:c"`` が同じ入力になるのを防ぐ)。
    """
    if not seed:
        raise ValueError("client secret seed must not be empty")
    if not realm or not client_id:
        raise ValueError("realm and client_id must not be empty")
    if ":" in realm or ":" in client_id:
        raise ValueError("realm and client_id must not contain ':'")
    digest = hmac.new(seed.encode("utf-8"), f"{realm}:{client_id}".encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def is_insecure_client_secret_seed(seed: str | None) -> bool:
    """シード値が未設定、または開発用の既定値かどうかを返す。

    Args:
        seed: 判定するシード値。

    Returns:
        bool: 未設定・空・既定値の場合に ``True``。
    """
    return not seed or seed == INSECURE_DEFAULT_CLIENT_SECRET_SEED


def client_secret_seed_from_env() -> str:
    """環境変数 ``KC_CLIENT_SECRET_SEED`` からシード値を読む。

    未設定または開発用の既定値の場合、``APP_ENV=development`` では警告を出して既定値を使う。
    それ以外の環境ではエラーにする (既定値のシードでは全テナントのシークレットが推測できるため)。

    Returns:
        str: シード値。

    Raises:
        RuntimeError: 本番相当の環境でシード値が未設定または既定値の場合。
    """
    seed = os.getenv(CLIENT_SECRET_SEED_ENV, "")
    if not is_insecure_client_secret_seed(seed):
        return seed
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env != "development":
        raise RuntimeError(f"{CLIENT_SECRET_SEED_ENV} が未設定または開発用の既定値です。APP_ENV={app_env} では使用できません。")
    logger.warning("%s が未設定または開発用の既定値です。本番環境では必ず変更してください。", CLIENT_SECRET_SEED_ENV)
    return INSECURE_DEFAULT_CLIENT_SECRET_SEED
