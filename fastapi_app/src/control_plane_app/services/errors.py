#!/usr/bin/env python
# coding:utf-8
"""テナントのライフサイクル操作（払い出し・停止・再開・削除）の例外。

FastAPI に依存しない。API 層（fastapi-api-schema 担当）は各例外の ``code`` と下表の HTTP ステータスで
Problem Details（03 §2）に変換する。

| 例外 | ``code`` | HTTP（03 §2） |
| --- | --- | --- |
| :class:`TenantValidationError` | ``invalid_tenant_input`` | 422 |
| :class:`InvalidTenantCodeError` | ``invalid_tenant_code`` | 422 |
| :class:`TenantNotFoundError` | ``tenant_not_found`` | 404 |
| :class:`TenantCodeAlreadyExistsError` | ``tenant_code_already_exists`` | 409 |
| :class:`InvalidTenantTransitionError` | ``invalid_tenant_transition`` | 409 |
| :class:`TenantOperationInProgressError` | ``tenant_operation_in_progress`` | 409 |
| :class:`DeletionGracePeriodNotElapsedError` | ``deletion_grace_period_not_elapsed`` | 409（API からは呼ばない想定） |
| :class:`TenantVersionConflictError` | ``tenant_version_conflict`` | 412 |
| :class:`ProvisioningFailedError` | ``tenant_provisioning_failed`` | 502 |
| :class:`TenantRealmOperationError` | ``tenant_realm_operation_failed`` | 502 |
| :class:`DeprovisioningFailedError` | ``tenant_deprovisioning_failed`` | 502（定期ジョブ） |

メッセージ・属性には一時パスワード・シークレット・``KeycloakAdminError.detail`` を含めない。
原因の例外は ``__cause__`` に残す（ログ出力用。永続化しないこと）。
"""
import uuid


class TenantServiceError(Exception):
    """テナントのライフサイクル操作の例外の基底。

    Attributes:
        code: 機械判定用のコード（Problem Details の ``code``）。
    """

    code: str = "tenant_service_error"


class TenantValidationError(TenantServiceError):
    """入力値が不正（テナントコード以外の項目）。

    Attributes:
        field: 不正な項目名（例: ``name``, ``initial_admin.email``）。
        reason: 理由（``required`` / ``too_long`` / ``format`` 等）。
    """

    code = "invalid_tenant_input"

    def __init__(self, field: str, reason: str):
        """例外を初期化する。

        Args:
            field: 不正な項目名。
            reason: 理由。
        """
        self.field = field
        self.reason = reason
        super().__init__(f"invalid {field}: {reason}")


class InvalidTenantCodeError(TenantValidationError):
    """テナントコードが 01 §5.1 の形式に合わない、または §5.2 の予約語。

    Attributes:
        field: 常に ``tenant_code``。
        reason: ``format`` / ``reserved``（:class:`modules.tenancy.tenant_code.TenantCodeViolation` の値）。
    """

    code = "invalid_tenant_code"

    def __init__(self, reason: str):
        """例外を初期化する。

        Args:
            reason: 理由。
        """
        super().__init__("tenant_code", reason)


class TenantNotFoundError(TenantServiceError):
    """テナントが存在しない。

    Attributes:
        tenant_id: 指定されたテナント ID。
    """

    code = "tenant_not_found"

    def __init__(self, tenant_id: uuid.UUID):
        """例外を初期化する。

        Args:
            tenant_id: 指定されたテナント ID。
        """
        self.tenant_id = tenant_id
        super().__init__(f"tenant not found: {tenant_id}")


class TenantCodeAlreadyExistsError(TenantServiceError):
    """テナントコード（またはレルム名）が既に使われている。削除済みテナントのコードも再利用しない（01 CP-OPS-09）。

    Attributes:
        tenant_code: 指定されたテナントコード。
    """

    code = "tenant_code_already_exists"

    def __init__(self, tenant_code: str):
        """例外を初期化する。

        Args:
            tenant_code: 指定されたテナントコード。
        """
        self.tenant_code = tenant_code
        super().__init__(f"tenant_code already exists: {tenant_code}")


class InvalidTenantTransitionError(TenantServiceError):
    """現在の状態からは要求された操作（状態遷移）ができない（01 §6.1）。

    Attributes:
        tenant_id: テナント ID。
        operation: 要求された操作（``suspend`` 等）。
        current_status: 現在の状態。
    """

    code = "invalid_tenant_transition"

    def __init__(self, tenant_id: uuid.UUID, operation: str, current_status: str):
        """例外を初期化する。

        Args:
            tenant_id: テナント ID。
            operation: 要求された操作。
            current_status: 現在の状態。
        """
        self.tenant_id = tenant_id
        self.operation = operation
        self.current_status = current_status
        super().__init__(f"cannot {operation} tenant {tenant_id} in status {current_status}")


class DeletionGracePeriodNotElapsedError(InvalidTenantTransitionError):
    """削除の猶予期間（30 日）が経過していないため物理削除できない（01 CP-OPS-07）。

    Attributes:
        deletable_at: 物理削除が可能になる日時（UTC）。
    """

    code = "deletion_grace_period_not_elapsed"

    def __init__(self, tenant_id: uuid.UUID, current_status: str, deletable_at: object):
        """例外を初期化する。

        Args:
            tenant_id: テナント ID。
            current_status: 現在の状態。
            deletable_at: 物理削除が可能になる日時。
        """
        super().__init__(tenant_id, "deprovision", current_status)
        self.deletable_at = deletable_at


class TenantOperationInProgressError(TenantServiceError):
    """同じテナントの払い出し・削除が実行中（ロックを取得できなかった。01 CP-ONB-07）。

    Attributes:
        tenant_code: テナントコード。
    """

    code = "tenant_operation_in_progress"

    def __init__(self, tenant_code: str):
        """例外を初期化する。

        Args:
            tenant_code: テナントコード。
        """
        self.tenant_code = tenant_code
        super().__init__(f"another operation is in progress for tenant_code {tenant_code}")


class TenantVersionConflictError(TenantServiceError):
    """楽観ロックの不一致（03 §5.2）。

    Attributes:
        tenant_id: テナント ID。
        expected_version: 呼び出し側が指定したバージョン（``If-Match``）。
        actual_version: 現在のバージョン。
    """

    code = "tenant_version_conflict"

    def __init__(self, tenant_id: uuid.UUID, expected_version: int, actual_version: int):
        """例外を初期化する。

        Args:
            tenant_id: テナント ID。
            expected_version: 呼び出し側が指定したバージョン。
            actual_version: 現在のバージョン。
        """
        self.tenant_id = tenant_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(f"version mismatch for tenant {tenant_id}: expected {expected_version}, actual {actual_version}")


class TenantExternalOperationError(TenantServiceError):
    """外部依存（Keycloak・AP DB）の操作に失敗した（502）。

    Attributes:
        tenant_id: テナント ID。
        step: 失敗したステップ名。
        error_summary: 秘匿値を含まないエラーの要約（払い出し履歴の ``error`` と同じ値）。
    """

    code = "tenant_external_operation_failed"

    def __init__(self, tenant_id: uuid.UUID, step: str, error_summary: str):
        """例外を初期化する。

        Args:
            tenant_id: テナント ID。
            step: 失敗したステップ名。
            error_summary: 秘匿値を含まないエラーの要約。
        """
        self.tenant_id = tenant_id
        self.step = step
        self.error_summary = error_summary
        super().__init__(f"{self.code}: tenant {tenant_id} at step {step} ({error_summary})")


class ProvisioningFailedError(TenantExternalOperationError):
    """払い出し（onboard / retry）が失敗し、テナントを ``FAILED`` にした。

    ``status`` は ``FAILED`` でコミット済み。``retry`` で再実行できる。
    """

    code = "tenant_provisioning_failed"


class TenantRealmOperationError(TenantExternalOperationError):
    """停止・再開・削除要求でのレルムの有効/無効の切り替えに失敗した。テナントの状態は変更していない。"""

    code = "tenant_realm_operation_failed"


class DeprovisioningFailedError(TenantExternalOperationError):
    """物理削除が失敗した。``DEPROVISIONING`` のまま残し、次回の定期ジョブで再試行する（01 CP-OPS-08）。"""

    code = "tenant_deprovisioning_failed"
