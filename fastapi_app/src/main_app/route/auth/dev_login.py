#!/usr/bin/env python
# coding:utf-8
"""開発用のログインバイパスエンドポイント。

Playwright テストや手動での動作確認時に、KeyCloak のログイン画面を経由せず
認証済み状態にするための仕組み。URL を開くだけで認証後の画面に着地できる。

    GET /api/auth/dev-login?as=<profile>&next=<path>

セキュリティ上の位置づけ:
    このエンドポイントは**認証済みセッションを無条件に発行する**。
    :meth:`~modules.auth.environment.KeyCloakEnvironmentVariables.is_dev_login_enabled`
    が真のときだけ ``app.py`` から登録され、無効時はルート自体が存在しない (404)。
    フロントエンド側の Vite モードによる出し分けは導線を消すだけであり、
    実際の防御はこのサーバー側のルート非登録が担う。

実現方式:
    KeyCloak の Direct Access Grant (パスワードグラント) で**本物のトークン**を取得し、
    通常のコールバックと同一の内容でセッションを作る。これにより、ロール・トークン更新・
    ログアウトが本番と同じコードパスを通るため、テストが実装を検証できる。

    KeyCloak 側のクライアントで ``directAccessGrantsEnabled`` が有効である必要がある
    (``python -m modules.keycloak_admin.cli`` が設定する。手順は ``tenant-provisioning`` スキル)。
"""
import logging

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.auth.session import SESSION_COOKIE_NAME, create_session, sign_session_id
from modules.auth.token import build_token_record, verify_id_token

logger = logging.getLogger(__name__)

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()

# 開発用ログインに使用する認証情報。
# TODO: 認証情報の退避場所が決まったらこの定義をそこへ移す。
#       ロール別のユーザーを増やす場合はここにプロファイルを追加する。
DEV_LOGIN_PROFILES: dict[str, dict[str, str]] = {
    "default": {"realm": "tenant-a", "username": "user001", "password": "ChangeMe123!"},
}

# ログイン後の既定の遷移先 (フロントエンドのパス)
DEFAULT_NEXT_PATH = "/button"


def _validate_next_path(next_path: str) -> str:
    """遷移先パスを検証する。

    ``next`` をそのままリダイレクトに使うとオープンリダイレクトになるため、
    **同一オリジン内のパスのみ**を許可する。``//example.com`` は
    プロトコル相対 URL として外部に飛ぶため拒否する。

    Args:
        next_path: クエリパラメータで受け取った遷移先。

    Returns:
        str: 検証済みのパス。

    Raises:
        ValueError: パス以外 (絶対 URL / プロトコル相対 URL) が指定された場合。
    """
    path = (next_path or DEFAULT_NEXT_PATH).strip()
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("next must be a path starting with '/'")
    return path


def _fetch_tokens(profile: dict[str, str]) -> dict:
    """プロファイルの認証情報で KeyCloak からトークンを取得する。

    Args:
        profile: ``realm`` / ``username`` / ``password`` を持つプロファイル。

    Returns:
        dict: トークンエンドポイントのレスポンス。

    Raises:
        HTTPException(502): KeyCloak への到達に失敗した場合。
        HTTPException(401): 認証情報が拒否された場合。
    """
    token_url = _config.build_realm_endpoint(_config.kc_internal_base, profile["realm"], "token")
    try:
        response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": _config.client_id,
                "client_secret": _config.client_secret,
                "username": profile["username"],
                "password": profile["password"],
                "scope": "openid profile email",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("dev-login: KeyCloak への接続に失敗しました: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach KeyCloak") from exc

    if response.status_code != 200:
        # 認証情報の誤り、または directAccessGrantsEnabled が無効な場合にここへ来る
        logger.warning("dev-login: token request failed (%s): %s", response.status_code, response.text[:200])
        raise HTTPException(status_code=401, detail="Dev login failed. Check credentials and directAccessGrantsEnabled.")

    return response.json()


@router.get("/dev-login", include_in_schema=False)
def dev_login(profile_name: str = Query(default="default", alias="as"), next_path: str = Query(default=DEFAULT_NEXT_PATH, alias="next")):
    """開発用の認証情報でログインし、認証済み状態でフロントエンドへ遷移する。

    通常のコールバック (:func:`~main_app.route.auth.apiapp.callback`) と
    **同一内容のセッション**を作るため、以降の挙動 (トークン更新・ログアウト) は
    通常のログインと変わらない。

    Args:
        profile_name: 使用するプロファイル名。クエリ ``as`` で指定する。
        next_path: ログイン後の遷移先パス。クエリ ``next`` で指定する。

    Returns:
        RedirectResponse(302): ``FRONTEND_URL + next`` へのリダイレクト。
                               ``rf_sid`` HttpOnly Cookie が付与される。

    Raises:
        HTTPException(400): プロファイルが存在しない、または ``next`` が不正な場合。
        HTTPException(401): KeyCloak が認証情報を拒否した場合。
        HTTPException(502): KeyCloak に到達できない場合。
    """
    profile = DEV_LOGIN_PROFILES.get(profile_name)
    if not profile:
        available = ", ".join(sorted(DEV_LOGIN_PROFILES))
        raise HTTPException(status_code=400, detail=f"Unknown profile: {profile_name}. Available: {available}")

    try:
        redirect_path = _validate_next_path(next_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token_data = _fetch_tokens(profile)
    realm = profile["realm"]

    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="id_token was not issued")

    # 通常のコールバックと同じく署名検証を行う。
    # パスワードグラントには nonce が無いため expected_nonce は None とする。
    try:
        claims = verify_id_token(
            id_token,
            jwks_uri=_config.build_jwks_uri(realm),
            audience=_config.client_id,
            allowed_issuers=_config.allowed_issuers(realm),
            expected_nonce=None,
        )
    except Exception as exc:
        logger.warning("dev-login: id_token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid id_token") from exc

    session_id = create_session(
        {
            "realm": realm,
            "tokens": build_token_record(token_data),
            "user": {
                "sub": claims.get("sub"),
                "preferred_username": claims.get("preferred_username"),
                "email": claims.get("email"),
                "realm": realm,
            },
        }
    )

    logger.warning("dev-login: プロファイル '%s' でセッションを発行しました", profile_name)

    response = RedirectResponse(url=f"{_config.frontend_url}{redirect_path}", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign_session_id(session_id),
        httponly=True,
        secure=_config.cookie_secure(),
        samesite="lax",
        path="/",
    )
    return response
