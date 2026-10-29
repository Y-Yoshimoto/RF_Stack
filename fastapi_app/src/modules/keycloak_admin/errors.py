"""Keycloak Admin API 操作の例外定義。

例外メッセージには**管理トークン・パスワード・クライアントシークレットを含めない**。
Keycloak のエラーレスポンスからは、診断に必要な既知のフィールド
(``error`` / ``error_description`` / ``errorMessage`` / ``field``) だけを抜き出して保持する。
"""
import httpx

# エラーレスポンスから抜き出すフィールド。これ以外 (トークンを含み得る本文全体など) は保持しない。
_SAFE_ERROR_FIELDS = ("error", "error_description", "errorMessage", "field")

# 本文が JSON でない場合に保持する最大文字数。
_MAX_TEXT_DETAIL_LENGTH = 200


class KeycloakAdminError(Exception):
    """Keycloak Admin API 操作の失敗を表す基底例外。

    Attributes:
        operation (str): 失敗した操作の説明 (例: ``create realm``)。
        status_code (int | None): HTTP ステータスコード。通信自体が失敗した場合は ``None``。
        detail (str): Keycloak が返したエラー内容の要約 (秘匿値を含まない)。
    """

    def __init__(self, operation: str, status_code: int | None = None, detail: str = ""):
        """例外を初期化する。

        Args:
            operation: 失敗した操作の説明。
            status_code: HTTP ステータスコード。
            detail: エラー内容の要約。
        """
        self.operation = operation
        self.status_code = status_code
        self.detail = detail
        message = f"Failed to {operation}."
        if status_code is not None:
            message += f" HTTP {status_code}"
        if detail:
            message += f" {detail}"
        super().__init__(message)


class KeycloakAdminAuthError(KeycloakAdminError):
    """管理トークンの取得に失敗したことを表す例外。"""


class KeycloakAdminTimeoutError(KeycloakAdminError):
    """リクエストのタイムアウト、または全体の締め切り超過を表す例外。"""


class KeycloakAdminConnectionError(KeycloakAdminError):
    """Keycloak への接続自体に失敗したことを表す例外。"""


def summarize_error_response(response: httpx.Response) -> str:
    """エラーレスポンスから秘匿値を含まない要約文字列を作る。

    Args:
        response: Keycloak からのレスポンス。

    Returns:
        str: 既知のエラーフィールドを ``key=value`` で連結した文字列。
             JSON でない場合は先頭の一部のみを返す。
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:_MAX_TEXT_DETAIL_LENGTH].strip()

    if not isinstance(body, dict):
        return ""
    parts = [f"{key}={body[key]}" for key in _SAFE_ERROR_FIELDS if body.get(key)]
    return ", ".join(parts)
