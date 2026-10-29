#!/usr/bin/env python
# coding:utf-8
"""共通のエラーコードと日本語メッセージ（03 §2）。

``HTTPException`` の ``detail``（英語の固定文字列や内部用のコード）を、利用者向けの Problem Details に
対応付ける表を持つ。表に無い ``detail`` は ``detail`` の文字列を返さず、ステータスごとの既定のメッセージにする
（内部情報が漏れないようにするため。元の文字列はログに残す）。

プレーン固有のエラー（例: テナントの払い出し）の表は各プレーンのモジュールが持つ。
"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProblemText:
    """エラーコードごとの表示文言。

    Attributes:
        status: HTTP ステータス。``None`` なら元のステータスを使う。
        title: 要約（日本語）。
        detail: 説明（日本語）。
    """

    title: str
    detail: str
    status: int | None = None


# エラーコード → 文言。
PROBLEM_TEXTS: dict[str, ProblemText] = {
    "bad_request": ProblemText("リクエストが不正です", "リクエストの内容を確認してください"),
    "unauthenticated": ProblemText("認証が必要です", "ログインしてください"),
    "session_expired": ProblemText("セッションの有効期限が切れました", "もう一度ログインしてください"),
    "forbidden": ProblemText("この操作を行う権限がありません", "必要な権限が付与されていません"),
    "csrf_validation_failed": ProblemText("リクエストを受け付けられません", "リクエストの送信元を確認できませんでした。画面を再読み込みして、もう一度お試しください"),
    "tenant_inactive": ProblemText("このテナントは現在利用できません", "テナントが停止中または削除要求中のため、利用できません。管理者にお問い合わせください"),
    "tenant_unavailable": ProblemText("このテナントを利用できません", "このテナントのアプリケーションを利用できません。もう一度ログインしてください"),
    "login_rejected": ProblemText("ログインできません", "ログインを完了できませんでした。管理者にお問い合わせください"),
    "not_found": ProblemText("リソースが見つかりません", "指定されたリソースは存在しないか、閲覧権限がありません"),
    "method_not_allowed": ProblemText("このメソッドは許可されていません", "指定されたパスでは、このメソッドは利用できません"),
    "conflict": ProblemText("リクエストが競合しています", "現在の状態ではこの操作を行えません"),
    "precondition_failed": ProblemText("前提条件を満たしていません", "リソースが他の操作により更新されています。最新の状態を取得してやり直してください"),
    "precondition_required": ProblemText("前提条件のヘッダーが必要です", "このリクエストには If-Match ヘッダーが必要です"),
    "validation_error": ProblemText("入力内容が不正です", "入力内容を確認してください"),
    "too_many_requests": ProblemText("リクエストが多すぎます", "しばらく待ってから、もう一度お試しください"),
    "internal_error": ProblemText("サーバーでエラーが発生しました", "時間をおいて、もう一度お試しください。解消しない場合は管理者にお問い合わせください"),
    "external_service_error": ProblemText("外部サービスとの通信に失敗しました", "外部サービスの処理に失敗しました。時間をおいて、もう一度お試しください"),
    "identity_provider_unreachable": ProblemText("認証サーバーに接続できません", "認証サーバーに接続できませんでした。時間をおいて、もう一度お試しください"),
    "service_unavailable": ProblemText("サービスを利用できません", "サービスが一時的に利用できません。時間をおいて、もう一度お試しください"),
    "gateway_timeout": ProblemText("処理がタイムアウトしました", "外部サービスの応答がありませんでした。時間をおいて、もう一度お試しください"),
    "invalid_auth_state": ProblemText("ログインを続行できません", "ログインの手続きが無効または期限切れです。最初からやり直してください"),
    "authorization_failed": ProblemText("ログインに失敗しました", "認証サーバーでの認可に失敗しました。もう一度お試しください"),
    "token_exchange_failed": ProblemText("ログインに失敗しました", "認証情報の交換に失敗しました。もう一度お試しください"),
    "invalid_token": ProblemText("ログインに失敗しました", "認証情報を検証できませんでした。もう一度お試しください"),
    "dev_login_failed": ProblemText("開発用ログインに失敗しました", "開発用ログインの認証情報を確認してください"),
    "e2e_cleanup_in_progress": ProblemText("後片付けが実行中です", "別の E2E データの後片付けが実行中です。完了してからやり直してください"),
}

# HTTP ステータス → 既定のエラーコード。
STATUS_DEFAULT_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    412: "precondition_failed",
    422: "validation_error",
    428: "precondition_required",
    429: "too_many_requests",
    500: "internal_error",
    502: "external_service_error",
    503: "service_unavailable",
    504: "gateway_timeout",
}

# 4xx / 5xx の既知でないステータスに使うコード。
FALLBACK_CLIENT_ERROR_CODE = "bad_request"
FALLBACK_SERVER_ERROR_CODE = "internal_error"

# ``HTTPException.detail``（既存コードが送出する固定文字列）→ エラーコード。
# 理由を区別して返したくないもの（無効なセッション・テナントの不一致など）は同じコードに集約する。
DETAIL_TO_CODE: dict[str, str] = {
    "Not authenticated": "unauthenticated",
    "Invalid session": "unauthenticated",
    "Invalid session payload": "unauthenticated",
    "Session expired": "session_expired",
    "Forbidden": "forbidden",
    "CSRF validation failed": "csrf_validation_failed",
    # modules.tenancy.resolver.TenantErrorCode。停止中だけ区別し、それ以外は存在有無を推測できないよう集約する
    "tenant_inactive": "tenant_inactive",
    "tenant_claim_missing": "tenant_unavailable",
    "tenant_claim_invalid": "tenant_unavailable",
    "tenant_not_found": "tenant_unavailable",
    "tenant_mismatch": "tenant_unavailable",
    # modules.auth.login.LOGIN_REJECTED_DETAIL
    "Login rejected": "login_rejected",
    "Invalid state": "invalid_auth_state",
    "Authorization failed": "authorization_failed",
    "Token exchange failed": "token_exchange_failed",
    "Invalid token response": "invalid_token",
    "Invalid token": "invalid_token",
    "Failed to reach KeyCloak": "identity_provider_unreachable",
}


def default_code_for_status(status: int) -> str:
    """HTTP ステータスの既定のエラーコードを返す。

    Args:
        status: HTTP ステータス。

    Returns:
        str: エラーコード。
    """
    code = STATUS_DEFAULT_CODES.get(status)
    if code is not None:
        return code
    return FALLBACK_SERVER_ERROR_CODE if status >= 500 else FALLBACK_CLIENT_ERROR_CODE


def resolve_http_exception_code(status: int, detail: object) -> str:
    """``HTTPException`` のステータスと ``detail`` からエラーコードを決める。

    Args:
        status: HTTP ステータス。
        detail: ``HTTPException.detail``。

    Returns:
        str: エラーコード。表に無い ``detail`` はステータスの既定のコード。
    """
    if isinstance(detail, str):
        if detail.startswith("Dev login failed"):
            return "dev_login_failed"
        code = DETAIL_TO_CODE.get(detail)
        if code is not None:
            return code
    return default_code_for_status(status)


def text_for_code(code: str, status: int) -> ProblemText:
    """エラーコードの文言を返す。表に無ければステータスの既定の文言。

    Args:
        code: エラーコード。
        status: HTTP ステータス。

    Returns:
        ProblemText: 文言。
    """
    text = PROBLEM_TEXTS.get(code)
    if text is not None:
        return text
    return PROBLEM_TEXTS[default_code_for_status(status)]
