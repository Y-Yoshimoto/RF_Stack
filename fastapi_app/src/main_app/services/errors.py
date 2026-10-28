#!/usr/bin/env python
# coding:utf-8
"""AP のユーザー・組織管理（01 §8 PF-USR / PF-ORG）とログイン時のユーザー同期の例外。

FastAPI に依存しない。API 層（fastapi-api-schema 担当）は各例外の ``code`` と下表の HTTP ステータスで
Problem Details（03 §2）に変換する。ログイン処理（auth-keycloak 担当）は下表の「ログイン時」の列に従う。

| 例外 | ``code`` | HTTP（03 §2） |
| --- | --- | --- |
| :class:`UserValidationError` | ``invalid_user_input`` | 422 |
| :class:`InvalidUserRoleError` | ``invalid_user_role`` | 422 |
| :class:`OrganizationValidationError` | ``invalid_organization_input`` | 422 |
| :class:`InvalidOrganizationMembersError` | ``invalid_organization_members`` | 422 |
| :class:`UserNotFoundError` | ``user_not_found`` | 404（他テナント・存在しないユーザーを区別しない） |
| :class:`OrganizationNotFoundError` | ``organization_not_found`` | 404（他テナント・存在しない・論理削除済みを区別しない） |
| :class:`UserAlreadyExistsError` | ``user_already_exists`` | 409（ユーザー名・メールアドレスの重複。テナント内） |
| :class:`OrganizationNameConflictError` | ``organization_name_already_exists`` | 409 |
| :class:`UserSelfModificationError` | ``user_self_modification_forbidden`` | 409（自分自身の無効化・``tenant_admin`` の解除） |
| :class:`UserVersionConflictError` | ``user_version_conflict`` | 412 |
| :class:`OrganizationVersionConflictError` | ``organization_version_conflict`` | 412 |
| :class:`IdentityProviderOperationError` | ``identity_provider_operation_failed`` | 502 |
| :class:`UserDeactivatedError` | ``user_deactivated`` | ログイン時: ログインを拒否（コールバックは ``login_rejected``）。各リクエスト時: 401 とセッション破棄 |
| :class:`UserNotSyncedError` | ``user_not_synced`` | 各リクエスト時: 401 とセッション破棄（再ログインで同期される） |

メッセージ・属性には一時パスワード・トークン・``KeycloakAdminError.detail`` を含めない。
原因の例外は ``__cause__`` に残す（ログ出力用。永続化しないこと）。
"""
import uuid
from collections.abc import Sequence


class AppServiceError(Exception):
    """AP のユーザー・組織管理の例外の基底。

    Attributes:
        code: 機械判定用のコード（Problem Details の ``code``）。
    """

    code: str = "app_service_error"


# --------------------------------------------------------------------------- 422
class AppValidationError(AppServiceError):
    """入力値が不正（422）の基底。

    Attributes:
        field: 不正な項目名（例: ``email``, ``name``）。
        reason: 理由（``required`` / ``too_long`` / ``format`` 等）。
    """

    code = "invalid_input"

    def __init__(self, field: str, reason: str):
        """例外を初期化する。

        Args:
            field: 不正な項目名。
            reason: 理由。
        """
        self.field = field
        self.reason = reason
        super().__init__(f"invalid {field}: {reason}")


class UserValidationError(AppValidationError):
    """ユーザーの入力値が不正。"""

    code = "invalid_user_input"


class InvalidUserRoleError(UserValidationError):
    """付与できないロールが指定された（付与できるのは ``tenant_admin`` / ``member`` のみ。01 §7.5）。

    Attributes:
        roles: 指定されたロールのうち付与できないもの。
    """

    code = "invalid_user_role"

    def __init__(self, roles: Sequence[str]):
        """例外を初期化する。

        Args:
            roles: 付与できないロール。
        """
        self.roles = tuple(roles)
        super().__init__("roles", "not_allowed")


class OrganizationValidationError(AppValidationError):
    """組織の入力値が不正。"""

    code = "invalid_organization_input"


class InvalidOrganizationMembersError(OrganizationValidationError):
    """組織のメンバーに、テナント内に存在しないユーザー（他テナントのユーザーを含む）が指定された。

    Attributes:
        user_ids: 存在しないユーザー ID（入力に含まれていた値のみ。存在の有無以上の情報は含めない）。
    """

    code = "invalid_organization_members"

    def __init__(self, user_ids: Sequence[uuid.UUID]):
        """例外を初期化する。

        Args:
            user_ids: 存在しないユーザー ID。
        """
        self.user_ids = tuple(user_ids)
        super().__init__("user_ids", "not_found")


# --------------------------------------------------------------------------- 404
class UserNotFoundError(AppServiceError):
    """ユーザーが存在しない（他テナントのユーザーも同じ扱い。03 §2）。

    Attributes:
        user_id: 指定されたユーザー ID。
    """

    code = "user_not_found"

    def __init__(self, user_id: uuid.UUID):
        """例外を初期化する。

        Args:
            user_id: 指定されたユーザー ID。
        """
        self.user_id = user_id
        super().__init__(f"user not found: {user_id}")


class OrganizationNotFoundError(AppServiceError):
    """組織が存在しない（他テナント・論理削除済みも同じ扱い。03 §2、§5.1）。

    Attributes:
        organization_id: 指定された組織 ID。
    """

    code = "organization_not_found"

    def __init__(self, organization_id: uuid.UUID):
        """例外を初期化する。

        Args:
            organization_id: 指定された組織 ID。
        """
        self.organization_id = organization_id
        super().__init__(f"organization not found: {organization_id}")


# --------------------------------------------------------------------------- 409
class UserAlreadyExistsError(AppServiceError):
    """ユーザー名またはメールアドレスが、テナント内（IdP のレルムまたは AP のユーザー）で既に使われている（01 PF-USR-06）。

    どちらが重複したかは区別しない（IdP の 409 は理由を区別できないため）。
    """

    code = "user_already_exists"

    def __init__(self) -> None:
        """例外を初期化する。"""
        super().__init__("username or email already exists in the tenant")


class OrganizationNameConflictError(AppServiceError):
    """組織名が、有効な組織の中で既に使われている（大文字小文字を区別しない）。

    Attributes:
        name: 指定された組織名。
    """

    code = "organization_name_already_exists"

    def __init__(self, name: str):
        """例外を初期化する。

        Args:
            name: 指定された組織名。
        """
        self.name = name
        super().__init__("organization name already exists")


class UserSelfModificationError(AppServiceError):
    """操作者が自分自身を無効化する、または自分の ``tenant_admin`` を外そうとした（テナントの管理者不在を防ぐ）。

    Attributes:
        operation: 拒否した操作（``deactivate`` / ``remove_tenant_admin``）。
    """

    code = "user_self_modification_forbidden"

    def __init__(self, operation: str):
        """例外を初期化する。

        Args:
            operation: 拒否した操作。
        """
        self.operation = operation
        super().__init__(f"cannot {operation} yourself")


# --------------------------------------------------------------------------- 412
class VersionConflictError(AppServiceError):
    """楽観ロックの不一致（03 §5.2）の基底。

    Attributes:
        resource_id: 対象の ID。
        expected_version: 呼び出し側が指定したバージョン（``If-Match``）。
        actual_version: 現在のバージョン。
    """

    code = "version_conflict"

    def __init__(self, resource_id: uuid.UUID, expected_version: int, actual_version: int):
        """例外を初期化する。

        Args:
            resource_id: 対象の ID。
            expected_version: 呼び出し側が指定したバージョン。
            actual_version: 現在のバージョン。
        """
        self.resource_id = resource_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(f"version mismatch for {resource_id}: expected {expected_version}, actual {actual_version}")


class UserVersionConflictError(VersionConflictError):
    """ユーザーの楽観ロックの不一致。"""

    code = "user_version_conflict"


class OrganizationVersionConflictError(VersionConflictError):
    """組織の楽観ロックの不一致。"""

    code = "organization_version_conflict"


# --------------------------------------------------------------------------- 502
class IdentityProviderOperationError(AppServiceError):
    """IdP（Keycloak）の操作に失敗した。AP の DB は変更していない（ロールバック済み）。

    Attributes:
        operation: 失敗した操作（``create_user`` / ``update_user`` 等）。
        error_summary: 秘匿値を含まないエラーの要約（``operation=...; error=<例外の型>; http_status=...``）。
    """

    code = "identity_provider_operation_failed"

    def __init__(self, operation: str, error_summary: str):
        """例外を初期化する。

        Args:
            operation: 失敗した操作。
            error_summary: 秘匿値を含まないエラーの要約。
        """
        self.operation = operation
        self.error_summary = error_summary
        super().__init__(f"{self.code}: {error_summary}")


# --------------------------------------------------------------------------- 認証（ログイン時・各リクエスト時）
class UserDeactivatedError(AppServiceError):
    """無効化されたユーザー（``t_user.is_active = false``）。ログイン・リクエストを拒否する（01 PF-USR-03）。

    Attributes:
        user_id: AP のユーザー ID。
    """

    code = "user_deactivated"

    def __init__(self, user_id: uuid.UUID):
        """例外を初期化する。

        Args:
            user_id: AP のユーザー ID。
        """
        self.user_id = user_id
        super().__init__(f"user is deactivated: {user_id}")


class UserNotSyncedError(AppServiceError):
    """セッションのユーザーに対応する AP のユーザー行が無い（ログイン時の同期より前に作られたセッション等）。

    ユーザー行は削除しないため、通常は起きない。セッションを破棄して再ログインさせる（ログイン時に同期される）。
    """

    code = "user_not_synced"

    def __init__(self) -> None:
        """例外を初期化する（IdP の利用者 ID は個人の識別子のため保持しない）。"""
        super().__init__("user row is not synced for the session")
