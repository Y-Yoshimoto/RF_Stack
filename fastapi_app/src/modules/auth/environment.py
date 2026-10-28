"""KeyCloak OIDC認証設定モジュール。

このモジュールは、KeyCloak との連携に必要な設定値を環境変数から
取得・管理するクラスを提供します。

あわせて次の安全策を提供します。

- :func:`validate_realm_name` — 外部入力の Realm 名を検証する。
- :meth:`KeyCloakEnvironmentVariables.validate_secrets` — 既定のままの秘密鍵で
  本番環境が起動することを防ぐ (fail fast)。
- :meth:`KeyCloakEnvironmentVariables.is_dev_login_enabled` — 開発用ログインバイパスの
  有効可否を判定する。
"""
import logging
import os
import re
from urllib.parse import urlsplit

from modules.keycloak_admin.client_secret import CLIENT_SECRET_SEED_ENV, INSECURE_DEFAULT_CLIENT_SECRET_SEED, derive_client_secret

from .plane import Plane
from .redirects import login_page_path, post_login_path

logger = logging.getLogger(__name__)

# Realm 名として許可する文字種。
# 外部入力をそのまま URL パスに連結するため、パス区切りや相対パス指定を弾く。
# fullmatch で使う ("$" は末尾の改行 1 つを許してしまうため、アンカーには頼らない)。
REALM_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

# 開発用の既定値。本番環境でこの値のままの場合は起動を止める。
INSECURE_DEFAULT_VALUES = {
    CLIENT_SECRET_SEED_ENV: INSECURE_DEFAULT_CLIENT_SECRET_SEED,
    "SESSION_SECRET_KEY": "change-me-session-secret",
}


def validate_realm_name(realm: str) -> str:
    """外部入力の Realm 名を検証し、正規化した値を返す。

    Realm 名は KeyCloak のエンドポイント URL のパスに直接連結されるため、
    未検証のまま扱うと ``../`` などでパスを変えられる。英数字・ハイフン・
    アンダースコアのみを許可する。

    Note:
        ログイン開始は Realm 名を外部から受け取らない (AP は tenant_code をテナントレジストリで
        解決し、CP は固定)。本関数はレジストリ等から得た値に対する多重防御として使う。

    Args:
        realm: 検証対象の Realm 名。

    Returns:
        str: 前後の空白を除去した Realm 名。

    Raises:
        ValueError: 空文字、または許可されない文字を含む場合 (末尾の改行も不可)。
    """
    realm_name = (realm or "").strip()
    if not REALM_NAME_PATTERN.fullmatch(realm_name):
        raise ValueError("realm must match ^[A-Za-z0-9_-]{1,64}$")
    return realm_name


def _origin_of(url: str) -> str | None:
    """URL から Origin (``scheme://host[:port]``、小文字) を取り出す。

    Args:
        url: 対象の URL。

    Returns:
        str | None: Origin。スキームまたはホストが無い場合は ``None``。
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


class KeyCloakEnvironmentVariables:
    """KeyCloak認証設定を環境変数から取得・管理するクラス。

    環境変数から認証関連設定を取得し、インスタンス属性として保持します。
    すべての設定値はコンストラクタで初期化される際に読み込まれます。

    Attributes:
        path_prefix (str): KeyCloak の HTTP コンテキストパス。
        kc_internal_base (str): コンテナ内部ネットワークからアクセスする KeyCloak のベース URL。
        kc_external_base (str): ブラウザからアクセスする KeyCloak の公開ベース URL。
        client_id (str): AP の OIDC クライアント ID (``KEYCLOAK_CLIENT_ID``、既定 ``fastapi-app``)。
        cp_client_id (str): CP の OIDC クライアント ID (``KEYCLOAK_CP_CLIENT_ID``、既定 ``fastapi-cp``)。
        client_secret_seed (str): クライアントシークレット導出用のシード (``KC_CLIENT_SECRET_SEED``)。
        callback_url (str): KeyCloak からのリダイレクト先 URL。
        frontend_url (str): ログイン/ログアウト後のリダイレクト先ベース URL。
        app_env (str): 実行環境名。``production`` の場合は秘密鍵の検証を厳格化する。
    """

    def __init__(self):
        """環境変数から KeyCloak 設定を初期化する。

        環境変数がない場合は、適切なデフォルト値を使用します。
        """
        # KeyCloak の HTTP コンテキストパス
        self.path_prefix = os.getenv("KEYCLOAK_HTTP_RELATIVE_PATH", "keycloak").strip("/")

        # コンテナ内部ネットワークからアクセスする KeyCloak のベース URL
        self.kc_internal_base = os.getenv("KEYCLOAK_URL", "http://keycloak_c:8080").rstrip("/")

        # ブラウザからアクセスする KeyCloak の公開ベース URL
        self.kc_external_base = os.getenv("KEYCLOAK_EXTERNAL_URL", "http://localhost:8080").rstrip("/")

        # OIDC クライアント ID (プレーン毎)
        self.client_id = os.getenv("KEYCLOAK_CLIENT_ID", "").strip() or "fastapi-app"
        self.cp_client_id = os.getenv("KEYCLOAK_CP_CLIENT_ID", "").strip() or "fastapi-cp"

        # クライアントシークレットは保存せず、シードとレルム名・クライアント ID から導出する (02 §3.3)。
        # 未設定時は開発用の既定値になる (validate_secrets が本番では起動を止める)。
        self.client_secret_seed = os.getenv(CLIENT_SECRET_SEED_ENV, "") or INSECURE_DEFAULT_CLIENT_SECRET_SEED

        # コールバック URL (Vite proxy 経由のブラウザアクセス URL)
        self.callback_url = os.getenv("APP_CALLBACK_URL", "http://localhost:5173/api/auth/callback")

        # フロントエンドのベース URL
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

        # 実行環境名 (development / production)
        self.app_env = os.getenv("APP_ENV", "development").strip().lower()

    def client_id_for(self, plane: Plane) -> str:
        """プレーンの OIDC クライアント ID を返す。

        Args:
            plane: プレーン。

        Returns:
            str: クライアント ID。
        """
        return self.cp_client_id if plane == Plane.CP else self.client_id

    def client_secret_for(self, plane: Plane, realm: str) -> str:
        """プレーンとレルムに対応するクライアントシークレットを導出する。

        戻り値は秘匿値のため、ログや例外メッセージに含めないこと。

        Args:
            plane: プレーン。
            realm: レルム名。

        Returns:
            str: クライアントシークレット。
        """
        return derive_client_secret(self.client_secret_seed, realm, self.client_id_for(plane))

    def frontend_redirect_url(self, path: str) -> str:
        """フロントエンドのパスを ``FRONTEND_URL`` と連結した URL にする。

        ホスト部は常に ``FRONTEND_URL`` とし、外部入力からは決めない (オープンリダイレクトにしない)。

        Args:
            path: ``/`` で始まるパス (クエリを含んでよい)。

        Returns:
            str: 遷移先 URL。
        """
        return f"{self.frontend_url}{path}"

    def post_login_url(self, plane: Plane, tenant_code: str | None = None) -> str:
        """ログイン完了後のフロントエンドの遷移先 URL を返す。

        AP は ``/{tenant_code}/``、CP は ``/cp/`` (01 §11.1)。AP で tenant_code が分からない場合はランディング (``/``)。

        Args:
            plane: プレーン。
            tenant_code: AP のテナントコード。

        Returns:
            str: 遷移先 URL。
        """
        return self.frontend_redirect_url(post_login_path(plane, tenant_code))

    def post_logout_url(self, plane: Plane, tenant_code: str | None = None) -> str:
        """ログアウト後のフロントエンドの遷移先 URL を返す。

        AP は ``/{tenant_code}/login``、CP は ``/cp/login`` (02 §3.1)。AP で tenant_code が
        分からない場合はランディング (``/``) とする。

        Args:
            plane: プレーン。
            tenant_code: AP のテナントコード。

        Returns:
            str: 遷移先 URL。
        """
        return self.frontend_redirect_url(login_page_path(plane, tenant_code))

    def trusted_origins(self) -> frozenset[str]:
        """変更系リクエストで許可する ``Origin`` の集合を返す (CSRF 対策)。

        ``FRONTEND_URL`` の Origin に加え、環境変数 ``CSRF_TRUSTED_ORIGINS`` (カンマ区切り) の値を許可する。
        Vite proxy 経由ではブラウザの Origin は ``FRONTEND_URL`` と一致するため、通常は追加設定は不要。
        ``vite preview`` (別ポート) から操作する場合などに追加する。

        Returns:
            frozenset[str]: 許可する Origin (小文字、末尾スラッシュなし)。
        """
        candidates = [self.frontend_url, *os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")]
        return frozenset(origin for origin in (_origin_of(url) for url in candidates if url.strip()) if origin)

    def build_realm_endpoint(self, base_url: str, realm: str, endpoint: str) -> str:
        """指定の KeyCloak エンドポイント URL を構築する。

        Args:
            base_url: KeyCloak のベース URL (``kc_internal_base`` または ``kc_external_base``).
            realm: リクエスト先の Realm 名。
            endpoint: ``auth`` / ``token`` / ``userinfo`` など OIDC エンドポイント名。

        Returns:
            str: 構築されたフル URL。
        """
        return f"{base_url}/{self.path_prefix}/realms/{realm}/protocol/openid-connect/{endpoint}"

    def build_issuer(self, base_url: str, realm: str) -> str:
        """指定の Realm の issuer (``iss`` クレーム) を構築する。

        Args:
            base_url: KeyCloak のベース URL。
            realm: Realm 名。

        Returns:
            str: ``{base}/{prefix}/realms/{realm}`` 形式の issuer 文字列。
        """
        return f"{base_url}/{self.path_prefix}/realms/{realm}"

    def allowed_issuers(self, realm: str) -> list[str]:
        """id_token の ``iss`` として許容する値の一覧を返す。

        本構成では、トークン交換をコンテナ内部 URL 経由で行う一方、
        ブラウザは外部公開 URL にアクセスする。KeyCloak のホスト名設定により
        ``iss`` がどちらのベース URL になるかが変わるため、両方を許容する。

        Args:
            realm: Realm 名。

        Returns:
            list[str]: 許容する issuer 文字列のリスト (重複は除去済み)。
        """
        issuers = [
            self.build_issuer(self.kc_internal_base, realm),
            self.build_issuer(self.kc_external_base, realm),
        ]
        return list(dict.fromkeys(issuers))

    def build_jwks_uri(self, realm: str) -> str:
        """id_token の署名検証に使う JWKS エンドポイント URL を返す。

        JWKS の取得はサーバー間通信のため、コンテナ内部 URL を使用する。

        Args:
            realm: Realm 名。

        Returns:
            str: JWKS エンドポイントの URL。
        """
        return self.build_realm_endpoint(self.kc_internal_base, realm, "certs")

    def is_production(self) -> bool:
        """本番環境として扱うかどうかを返す。

        Returns:
            bool: ``APP_ENV`` が ``development`` 以外の場合に ``True``。
        """
        return self.app_env != "development"

    def cookie_secure(self) -> bool:
        """セッション Cookie に ``Secure`` 属性を付けるかどうかを返す。

        ``Secure`` 付きの Cookie は HTTPS でしか送信されない。開発環境は
        ``http://localhost`` で動作するため付与すると Cookie が保持されず、
        ログインが成立しなくなる。実行環境から導出する。

        Returns:
            bool: 本番環境 (``APP_ENV`` が ``development`` 以外) の場合は ``True``。
        """
        return self.is_production()

    def is_dev_login_enabled(self) -> bool:
        """開発用ログインバイパスを有効にするかどうかを返す。

        このバイパスは**認証済みセッションを無条件に発行する**ため、
        誤って本番で有効化されないよう二重の条件を課す。

        1. ``APP_ENV`` が ``development`` であること
        2. ``AUTH_DEV_LOGIN_ENABLED`` が明示的に真であること

        Returns:
            bool: 両方を満たす場合のみ ``True``。
        """
        if self.is_production():
            return False
        return os.getenv("AUTH_DEV_LOGIN_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")

    def validate_dev_login(self) -> None:
        """開発用ログインバイパスが本番で有効化されていないことを検証する。

        :meth:`is_dev_login_enabled` は本番では常に ``False`` を返すが、
        「本番のつもりで有効化した」という設定ミスを黙って無視すると
        バイパスが効かない理由が分からなくなる。明示的に停止して気づけるようにする。

        Raises:
            RuntimeError: 本番環境で ``AUTH_DEV_LOGIN_ENABLED`` が真の場合。
        """
        requested = os.getenv("AUTH_DEV_LOGIN_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
        if requested and self.is_production():
            raise RuntimeError(
                f"AUTH_DEV_LOGIN_ENABLED は APP_ENV=development でのみ使用できます。APP_ENV={self.app_env} では起動できません。"
            )
        if self.is_dev_login_enabled():
            logger.warning(
                "開発用ログインバイパスが有効です (/api/auth/dev-login)。認証済みセッションを無条件に発行するため、開発環境でのみ使用してください。"
            )

    def validate_secrets(self) -> None:
        """秘密鍵が開発用の既定値のままでないことを検証する。

        既定値のまま本番環境が起動すると、セッション Cookie の署名鍵が
        公開値となりセッションを偽造できてしまう。クライアントシークレットのシードが既定値だと、
        全テナントのクライアントシークレットが推測できてしまう。これを起動時に検出して止める。

        開発環境 (``APP_ENV=development``) では警告ログのみを出力し、起動は妨げない。

        Raises:
            RuntimeError: 本番環境で秘密鍵が未設定または既定値のままの場合。
        """
        current_values = {
            CLIENT_SECRET_SEED_ENV: self.client_secret_seed,
            "SESSION_SECRET_KEY": os.getenv("SESSION_SECRET_KEY", ""),
        }
        insecure_names = [
            name
            for name, insecure_value in INSECURE_DEFAULT_VALUES.items()
            if not current_values[name] or current_values[name] == insecure_value
        ]
        if not insecure_names:
            return

        message = f"開発用の既定値のままの環境変数があります: {', '.join(insecure_names)}"
        if self.is_production():
            raise RuntimeError(f"{message}。APP_ENV={self.app_env} では起動できません。")
        logger.warning("%s。本番環境では必ず変更してください。", message)
