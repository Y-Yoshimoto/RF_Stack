"""RFC 9457（Problem Details）に統一するエラー応答と、リクエスト ID（03 §2、02 §5.1）。

モジュール構成:
    - ``problem``    — :class:`ProblemError`（ルーターから送出する例外）、``ProblemDetails``（スキーマ）、レスポンスの組み立て。
    - ``catalog``    — 共通のエラーコードと日本語メッセージ、``HTTPException.detail`` の対応表。
    - ``handlers``   — FastAPI の例外ハンドラ（``register_exception_handlers``）。プレーン固有の例外の変換用に
      ``problem_exception_handler`` を提供する。
    - ``openapi``    — OpenAPI への反映（``install_problem_openapi``、``problem_responses``）。
    - ``request_id`` — ``X-Request-ID`` の受け取り・生成と保持（``RequestIdMiddleware``、``get_request_id``）。

本パッケージは re-export を行わない。各モジュールから明示的に import すること::

    from modules.errors.problem import ProblemError
"""
