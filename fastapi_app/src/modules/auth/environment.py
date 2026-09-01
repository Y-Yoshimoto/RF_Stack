"""KeyCloak OIDC認証設定モジュール。

このモジュールは、KeyCloak との連携に必要な設定値を環境変数から
取得・管理するクラスを提供します。

あわせて次の安全策を提供します。

- :func:`validate_realm_name` — 外部入力の Realm 名を検証する。
- :meth:`KeyCloakEnvironmentVariables.validate_secrets` — 既定のままの秘密鍵で
  本番環境が起動することを防ぐ (fail fast)。
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# Realm 名として許可する文字種。
# 外部入力をそのまま URL パスに連結するため、パス区切りや相対パス指定を弾く。
REALM_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 開発用の既定値。本番環境でこの値のままの場合は起動を止める。
INSECURE_DEFAULT_VALUES = {
    "KEYCLOAK_CLIENT_SECRET": "change-me",
    "SESSION_SECRET_KEY": "change-me-session-secret",
}


def validate_realm_name(realm: str) -> str:
    """外部入力の Realm 名を検証し、正規化した値を返す。

    Realm 名は KeyCloak のエンドポイント URL のパスに直接連結されるため、
    未検証のまま扱うと ``../`` などでパスを変えられる。英数字・ハイフン・
    アンダースコアのみを許可する。

    Note:
        本プロジェクトはマルチテナント構成であり、将来的には
        ``t_tenant`` テーブルとの突き合わせによる許可リスト方式に
        置き換えることが望ましい。本関数はその前段の最低限の防御である。

    Args:
        realm: 検証対象の Realm 名 (クエリパラメータ等の外部入力)。

    Returns:
        str: 前後の空白を除去した Realm 名。

    Raises:
        ValueError: 空文字、または許可されない文字を含む場合。
    """
    realm_name = (realm or "").strip()
    if not REALM_NAME_PATTERN.match(realm_name):
        raise ValueError("realm must match ^[A-Za-z0-9_-]{1,64}$")
    return realm_name


class KeyCloakEnvironmentVariables:
    """KeyCloak認証設定を環境変数から取得・管理するクラス。

    環境変数から認証関連設定を取得し、インスタンス属性として保持します。
    すべての設定値はコンストラクタで初期化される際に読み込まれます。

    Attributes:
        path_prefix (str): KeyCloak の HTTP コンテキストパス。
        kc_internal_base (str): コンテナ内部ネットワークからアクセスする KeyCloak のベース URL。
        kc_external_base (str): ブラウザからアクセスする KeyCloak の公開ベース URL。
        client_id (str): OIDC クライアント ID。
        client_secret (str): OIDC クライアントシークレット。
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

        # OIDC クライアント ID とシークレット
        self.client_id = os.getenv("KEYCLOAK_CLIENT_ID", "fastapi-app")
        self.client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET", "change-me")

        # コールバック URL (Vite proxy 経由のブラウザアクセス URL)
        self.callback_url = os.getenv("APP_CALLBACK_URL", "http://localhost:5173/api/auth/callback")

        # フロントエンドのベース URL
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

        # 実行環境名 (development / production)
        self.app_env = os.getenv("APP_ENV", "development").strip().lower()

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

    def validate_secrets(self) -> None:
        """秘密鍵が開発用の既定値のままでないことを検証する。

        既定値のまま本番環境が起動すると、セッション Cookie の署名鍵が
        公開値となりセッションを偽造できてしまう。これを起動時に検出して止める。

        開発環境 (``APP_ENV=development``) では警告ログのみを出力し、起動は妨げない。

        Raises:
            RuntimeError: 本番環境で秘密鍵が未設定または既定値のままの場合。
        """
        current_values = {
            "KEYCLOAK_CLIENT_SECRET": self.client_secret,
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
