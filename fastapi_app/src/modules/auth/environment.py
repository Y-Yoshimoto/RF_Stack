"""KeyCloak OIDC認証設定モジュール。

このモジュールは、KeyCloak との連携に必要な設定値を環境変数から
取得・管理するクラスを提供します。
"""
import os

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
