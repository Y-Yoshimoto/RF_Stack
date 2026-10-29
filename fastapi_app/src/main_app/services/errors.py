#!/usr/bin/env python
# coding:utf-8
"""AP のユーザー・組織管理（01 §8 PF-USR / PF-ORG）、ログイン時のユーザー同期、ToDo（docs/spec/ToDoApp.md）の例外。

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
| :class:`TodoValidationError` | ``invalid_todo_input`` | 422（``field`` / ``reason``。例: ``organization_ids`` / ``required``、``assignee_ids`` / ``too_many``） |
| :class:`InvalidTodoAssigneesError` | ``invalid_todo_assignees`` | 422（``user_ids`` と ``reason``: ``not_found`` = テナント内に無い（他テナントを含む）/ ``inactive`` = 無効化されたユーザーの新規割り当て） |
| :class:`InvalidTodoOrganizationsError` | ``invalid_todo_organizations`` | 422（``organization_ids``。テナント内に無い・論理削除済みの組織を新たに公開先にした） |
| :class:`TodoNotFoundError` | ``todo_not_found`` | 404（他テナント・存在しない・論理削除済み・**閲覧範囲外**を区別しない。03 §2） |
| :class:`TodoPermissionDeniedError` | ``todo_operation_forbidden`` | 403（閲覧はできるが操作の権限が無い。``operation`` は ``todo_policy.TodoOperation`` の値） |
| :class:`TodoVersionConflictError` | ``todo_version_conflict`` | 412 |

メッセージ・属性には一時パスワード・トークン・``KeycloakAdminError.detail`` を含めない。
原因の例外は ``__cause__`` に残す（ログ出力用。永続化しないこと）。
"""
import uuid
from collections.abc import Sequence


class AppServiceError(Exception):
    """AP のサービス層（ユーザー・組織管理、ToDo）の例外の基底。

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


class TodoValidationError(AppValidationError):
    """ToDo の入力値が不正（AP-TODO-04、AP-VIS-07、AP-ASN-01 等）。"""

    code = "invalid_todo_input"


class InvalidTodoAssigneesError(TodoValidationError):
    """担当者に指定できないユーザーが含まれる（AP-ASN-02）。

    Attributes:
        user_ids: 指定できないユーザー ID（入力に含まれていた値のみ）。
        reason: ``not_found``（テナント内に存在しない。他テナントのユーザーを含む）/ ``inactive``（無効化されたユーザーを新たに割り当てようとした）。
    """

    code = "invalid_todo_assignees"

    def __init__(self, user_ids: Sequence[uuid.UUID], reason: str, *, field: str = "assignee_ids"):
        """例外を初期化する。

        Args:
            user_ids: 指定できないユーザー ID。
            reason: ``not_found`` / ``inactive``。
            field: 入力の項目名（作成は ``assignee_ids``、全置換は ``user_ids``）。
        """
        self.user_ids = tuple(user_ids)
        super().__init__(field, reason)


class InvalidTodoOrganizationsError(TodoValidationError):
    """公開先に指定できない組織が含まれる（テナント内に存在しない・論理削除済みの組織を新たに指定した）。

    Attributes:
        organization_ids: 指定できない組織 ID（入力に含まれていた値のみ）。
    """

    code = "invalid_todo_organizations"

    def __init__(self, organization_ids: Sequence[uuid.UUID]):
        """例外を初期化する。

        Args:
            organization_ids: 指定できない組織 ID。
        """
        self.organization_ids = tuple(organization_ids)
        super().__init__("organization_ids", "not_found")


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


class TodoNotFoundError(AppServiceError):
    """ToDo が存在しない。他テナント・論理削除済み・**閲覧範囲外**も同じ扱い（存在を明かさない。03 §2、ToDoApp.md §3）。

    Attributes:
        todo_id: 指定された ToDo ID。
    """

    code = "todo_not_found"

    def __init__(self, todo_id: uuid.UUID):
        """例外を初期化する。

        Args:
            todo_id: 指定された ToDo ID。
        """
        self.todo_id = todo_id
        super().__init__(f"todo not found: {todo_id}")


# --------------------------------------------------------------------------- 403
class TodoPermissionDeniedError(AppServiceError):
    """閲覧できる ToDo に対して、操作の権限が無い（ToDoApp.md §3）。

    Attributes:
        todo_id: ToDo ID。
        operation: 拒否した操作（``edit_fields`` / ``change_status`` / ``change_visibility`` / ``change_assignees`` / ``delete``）。
    """

    code = "todo_operation_forbidden"

    def __init__(self, todo_id: uuid.UUID, operation: str):
        """例外を初期化する。

        Args:
            todo_id: ToDo ID。
            operation: 拒否した操作。
        """
        self.todo_id = todo_id
        self.operation = operation
        super().__init__(f"operation {operation} is not allowed for todo {todo_id}")


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


class TodoVersionConflictError(VersionConflictError):
    """ToDo の楽観ロックの不一致（AP-TODO-08）。"""

    code = "todo_version_conflict"


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
