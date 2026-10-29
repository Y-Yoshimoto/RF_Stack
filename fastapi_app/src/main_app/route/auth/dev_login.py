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

テナントレジストリとの照合とユーザー同期 (AP のプロファイル):
    通常のコールバックと同じく、プロファイルのレルムをレジストリで ACTIVE なテナントに解決し
    (未登録・ACTIVE でない・テナントコードの食い違いは 403)、トークンの ``tenant_id`` クレームとの一致を確認する。
    セッションを作る前に、そのテナントのコンテキストで AP のユーザー行を同期する
    (:func:`~main_app.route.auth.login_sync.sync_app_user_on_login`。01 PF-USR-04 / 05)。
    無効化されたユーザーは 403 (``Login rejected``) でセッションを作らない。DB に接続できない場合は
    共通の例外ハンドラにより 503 (``service_unavailable``) になる。CP のプロファイルでは同期しない。
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from main_app.route.auth.login_sync import sync_app_user_on_login
from main_app.services.errors import UserDeactivatedError
from modules.auth.dev_profiles import DEFAULT_DEV_PROFILE, DEV_PROFILES, DevUser
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.auth.login import LOGIN_REJECTED_DETAIL, build_login_session
from modules.auth.plane import SESSION_COOKIE_NAMES, Plane
from modules.auth.redirects import post_login_path
from modules.auth.session import create_session, delete_session, set_session_cookie, unsign_session_id
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord, TenantRegistry, is_active
from modules.tenancy.resolver import TenantErrorCode

logger = logging.getLogger(__name__)

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()


def default_next_path(profile: DevUser) -> str:
    """``next`` を省略したときの遷移先パスを返す。

    プロファイルに ``next_path`` があればそれを、無ければ通常のログイン成功時と同じ遷移先
    (AP: ``/{tenant_code}/``、CP: ``/cp/``。:func:`~modules.auth.redirects.post_login_path`) とする。

    Args:
        profile: プロファイル。

    Returns:
        str: パス。
    """
    return profile.next_path or post_login_path(profile.plane, profile.tenant_code)


def _validate_next_path(next_path: str | None, default: str) -> str:
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


def _resolve_app_tenant(profile: DevUser, registry: TenantRegistry) -> TenantRecord:
    """AP のプロファイルのレルムを、レジストリで ACTIVE なテナントに解決する。

    Args:
        profile: AP のプロファイル。
        registry: テナントレジストリ。

    Returns:
        TenantRecord: テナント。

    Raises:
        HTTPException(403): 未登録 (``tenant_not_found``)、ACTIVE でない (``tenant_inactive``)、
            レルムのテナントコードがプロファイルと食い違う (``tenant_mismatch``) 場合。
    """
    record = registry.get_by_realm(profile.realm)
    if record is None:
        raise HTTPException(status_code=403, detail=TenantErrorCode.NOT_FOUND.value)
    if record.tenant_code != profile.tenant_code:
        raise HTTPException(status_code=403, detail=TenantErrorCode.MISMATCH.value)
    if not is_active(record):
        raise HTTPException(status_code=403, detail=TenantErrorCode.INACTIVE.value)
    return record


@router.get("/dev-login", include_in_schema=False)
def dev_login(
    request: Request,
    profile_name: str = Query(default=DEFAULT_DEV_PROFILE, alias="as"),
    next_path: str | None = Query(default=None, alias="next"),
    registry: TenantRegistry = Depends(get_tenant_registry),
):
    """開発用の認証情報でログインし、認証済み状態でフロントエンドへ遷移する。

    通常のコールバック (:func:`~main_app.route.auth.apiapp.callback`) と
    **同一内容のセッション** をプロファイルのプレーンに作るため、以降の挙動 (トークン更新・ログアウト) は
    通常のログインと変わらない。

    Args:
        request: リクエスト。プロファイルのプレーンの既存セッション Cookie (``rf_sid_app`` / ``rf_sid_cp``) を読み、破棄する。
        profile_name: 使用するプロファイル名。クエリ ``as`` で指定する (省略時 ``alpha-admin``)。
        next_path: ログイン後の遷移先パス。クエリ ``next`` で指定する。省略時は :func:`default_next_path`
            (AP: ``/{tenant_code}/``、CP: ``/cp/``)。
        registry: テナントレジストリ (AP のプロファイルのテナントの確認に使う)。

    Returns:
        RedirectResponse(302): ``FRONTEND_URL + next`` へのリダイレクト。
                               プレーンのセッション Cookie (``rf_sid_app`` / ``rf_sid_cp``) が付与される。

    Raises:
        HTTPException(400): プロファイルが存在しない、または ``next`` が不正な場合。
        HTTPException(401): KeyCloak が認証情報を拒否した、またはトークンの検証に失敗した場合。
        HTTPException(403): CP のプロファイルが CP のロールを持たない、AP のテナントが ACTIVE でない・
            ``tenant_id`` クレームが一致しない、または AP で無効化されたユーザーの場合。
        HTTPException(502): KeyCloak に到達できない場合。
        sqlalchemy.exc.OperationalError: AP の DB に接続できない場合 (共通の例外ハンドラで 503)。
    """
    profile = DEV_PROFILES.get(profile_name)
    if not profile:
        available = ", ".join(sorted(DEV_PROFILES))
        raise HTTPException(status_code=400, detail=f"Unknown profile: {profile_name}. Available: {available}")

    try:
        redirect_path = _validate_next_path(next_path, default_next_path(profile))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    app_record = _resolve_app_tenant(profile, registry) if profile.plane == Plane.APP else None

    token_data = _fetch_tokens(profile)
    # パスワードグラントには nonce が無いため expected_nonce は None とする。
    session_data = build_login_session(
        _config,
        profile.plane,
        profile.realm,
        token_data,
        expected_nonce=None,
        tenant_code=profile.tenant_code,
        expected_tenant_id=str(app_record.tenant_id) if app_record is not None else None,
    )

    if app_record is not None:
        # AP のユーザー行の同期 (通常のコールバックと同じ)。無効化されたユーザーにはセッションを作らない。
        try:
            sync_app_user_on_login(session_data, tenant_id=app_record.tenant_id, tenant_code=app_record.tenant_code)
        except UserDeactivatedError as exc:
            logger.warning("dev-login: 無効化されたユーザーのためログインを拒否しました: profile=%s user_id=%s", profile_name, exc.user_id)
            raise HTTPException(status_code=403, detail=LOGIN_REJECTED_DETAIL) from exc

    # 同じプレーンの既存セッションを破棄してから新しいセッションを発行する
    old_cookie = request.cookies.get(SESSION_COOKIE_NAMES[profile.plane])
    old_session_id = unsign_session_id(profile.plane, old_cookie) if old_cookie else None
    if old_session_id:
        delete_session(profile.plane, old_session_id)
    session_id = create_session(profile.plane, session_data)

    logger.warning("dev-login: プロファイル '%s' (plane=%s) でセッションを発行しました", profile_name, profile.plane.value)

    response = RedirectResponse(url=_config.frontend_redirect_url(redirect_path), status_code=302)
    set_session_cookie(response, profile.plane, session_id, secure=_config.cookie_secure())
    return response
