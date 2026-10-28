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

    KeyCloak 側のクライアントで ``directAccessGrantsEnabled`` が有効であり、クライアントシークレットが
    ``KC_CLIENT_SECRET_SEED`` からの導出値である必要がある
    (``python -m modules.keycloak_admin.cli`` が設定する。手順は ``tenant-provisioning`` スキル)。

プロファイル:
    開発用の認証情報は :mod:`modules.auth.dev_profiles` に 1 箇所で定義し、シードと共有する (02 §7.1)。
    プロファイルは :data:`~modules.auth.dev_profiles.DEV_PROFILES` (02 §7.2 の ``cp-admin`` / ``cp-viewer`` /
    ``alpha-admin`` / ``alpha-member`` / ``beta-member``)。``as`` 省略時は ``alpha-admin``。
    レルム・ユーザーはシード (CP の払い出しサービスを CLI から呼ぶもの) で作成しておく。

    CP のプロファイルは ``saas_admin`` / ``saas_viewer`` のいずれかのロールを持たないと 403 になる
    (通常のコールバックと同じ検証)。

テナントレジストリとの照合:
    開発用ログインはレジストリを引かない。トークンに ``tenant_id`` クレームがあればセッションに載せる。
    AP の ``/api/v1`` はリクエスト毎にテナントコンテキストの依存関数がレジストリと照合するため、
    未登録のテナントはそこで拒否される。
"""
import logging

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import RedirectResponse

from modules.auth.dev_profiles import DEFAULT_DEV_PROFILE, DEV_PROFILES, DevUser
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.auth.login import build_login_session
from modules.auth.plane import Plane
from modules.auth.session import create_session, delete_session, set_session_cookie, unsign_session_id

logger = logging.getLogger(__name__)

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()


# ログイン後の既定の遷移先 (フロントエンドのパス)
DEFAULT_NEXT_PATH = "/button"
DEFAULT_NEXT_PATHS: dict[Plane, str] = {Plane.APP: DEFAULT_NEXT_PATH, Plane.CP: "/cp/"}


def _validate_next_path(next_path: str | None, default: str = DEFAULT_NEXT_PATH) -> str:
    """遷移先パスを検証する。

    ``next`` をそのままリダイレクトに使うとオープンリダイレクトになるため、
    **同一オリジン内のパスのみ**を許可する。``//example.com`` は
    プロトコル相対 URL として外部に飛ぶため拒否する。``\\`` もブラウザが ``/`` と
    解釈するため拒否する。

    Args:
        next_path: クエリパラメータで受け取った遷移先。空なら ``default``。
        default: 既定の遷移先。

    Returns:
        str: 検証済みのパス。

    Raises:
        ValueError: パス以外 (絶対 URL / プロトコル相対 URL) が指定された場合。
    """
    path = (next_path or default).strip()
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise ValueError("next must be a path starting with '/'")
    return path


def _fetch_tokens(profile: DevUser) -> dict:
    """プロファイルの認証情報で KeyCloak からトークンを取得する。

    Args:
        profile: プロファイル。

    Returns:
        dict: トークンエンドポイントのレスポンス。

    Raises:
        HTTPException(502): KeyCloak への到達に失敗した場合。
        HTTPException(401): 認証情報が拒否された場合。
    """
    token_url = _config.build_realm_endpoint(_config.kc_internal_base, profile.realm, "token")
    try:
        response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": _config.client_id_for(profile.plane),
                "client_secret": _config.client_secret_for(profile.plane, profile.realm),
                "username": profile.username,
                "password": profile.password,
                "scope": "openid profile email",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("dev-login: KeyCloak への接続に失敗しました: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Failed to reach KeyCloak") from exc

    if response.status_code != 200:
        # 認証情報の誤り、シークレットの不一致、directAccessGrantsEnabled が無効、
        # ユーザープロフィールの未設定 (Account is not fully set up) などでここへ来る。
        # error / error_description はトークン等の秘匿値を含まない。
        try:
            body = response.json()
        except ValueError:
            body = {}
        logger.warning("dev-login: token request failed (%s): error=%s description=%s", response.status_code, body.get("error"), body.get("error_description"))
        raise HTTPException(status_code=401, detail="Dev login failed. Check credentials, client secret seed and directAccessGrantsEnabled.")

    return response.json()


@router.get("/dev-login", include_in_schema=False)
def dev_login(
    profile_name: str = Query(default=DEFAULT_DEV_PROFILE, alias="as"),
    next_path: str | None = Query(default=None, alias="next"),
    rf_sid_app: str | None = Cookie(default=None),
    rf_sid_cp: str | None = Cookie(default=None),
):
    """開発用の認証情報でログインし、認証済み状態でフロントエンドへ遷移する。

    通常のコールバック (:func:`~main_app.route.auth.apiapp.callback`) と
    **同一内容のセッション** をプロファイルのプレーンに作るため、以降の挙動 (トークン更新・ログアウト) は
    通常のログインと変わらない。

    Args:
        profile_name: 使用するプロファイル名。クエリ ``as`` で指定する (省略時 ``alpha-admin``)。
        next_path: ログイン後の遷移先パス。クエリ ``next`` で指定する。省略時はプレーンの既定。
        rf_sid_app: 既存の AP セッション Cookie (AP でログインする場合は破棄する)。
        rf_sid_cp: 既存の CP セッション Cookie (CP でログインする場合は破棄する)。

    Returns:
        RedirectResponse(302): ``FRONTEND_URL + next`` へのリダイレクト。
                               プレーンのセッション Cookie (``rf_sid_app`` / ``rf_sid_cp``) が付与される。

    Raises:
        HTTPException(400): プロファイルが存在しない、または ``next`` が不正な場合。
        HTTPException(401): KeyCloak が認証情報を拒否した、またはトークンの検証に失敗した場合。
        HTTPException(403): CP のプロファイルが CP のロールを持たない場合。
        HTTPException(502): KeyCloak に到達できない場合。
    """
    profile = DEV_PROFILES.get(profile_name)
    if not profile:
        available = ", ".join(sorted(DEV_PROFILES))
        raise HTTPException(status_code=400, detail=f"Unknown profile: {profile_name}. Available: {available}")

    try:
        redirect_path = _validate_next_path(next_path, profile.next_path or DEFAULT_NEXT_PATHS[profile.plane])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token_data = _fetch_tokens(profile)
    # パスワードグラントには nonce が無いため expected_nonce は None とする。
    session_data = build_login_session(_config, profile.plane, profile.realm, token_data, expected_nonce=None, tenant_code=profile.tenant_code)

    # 同じプレーンの既存セッションを破棄してから新しいセッションを発行する
    old_cookie = rf_sid_app if profile.plane == Plane.APP else rf_sid_cp
    old_session_id = unsign_session_id(profile.plane, old_cookie) if old_cookie else None
    if old_session_id:
        delete_session(profile.plane, old_session_id)
    session_id = create_session(profile.plane, session_data)

    logger.warning("dev-login: プロファイル '%s' (plane=%s) でセッションを発行しました", profile_name, profile.plane.value)

    response = RedirectResponse(url=f"{_config.frontend_url}{redirect_path}", status_code=302)
    set_session_cookie(response, profile.plane, session_id, secure=_config.cookie_secure())
    return response
