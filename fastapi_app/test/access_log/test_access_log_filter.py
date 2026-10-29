"""アクセスログから認可コード等のクエリを除くフィルタ(access_log_filter)のテスト。"""
import logging

import pytest

from access_log_filter import RedactAccessQueryFilter, redact_path


@pytest.mark.parametrize(
    ("full_path", "expected"),
    [
        ("/api/auth/callback?code=abc&state=xyz", "/api/auth/callback"),
        ("/api/auth/login?next=%2Ftodos", "/api/auth/login"),
        ("/api/v1/todos", "/api/v1/todos"),
        ("/api/v1/todos?limit=10&cursor=abc", "/api/v1/todos?limit=10&cursor=abc"),
        ("/api/v1/x?q=abc&access_token=TOK", "/api/v1/x?q=abc&access_token=***"),
    ],
)
def test_redact_path(full_path: str, expected: str) -> None:
    assert redact_path(full_path) == expected


def test_filter_rewrites_uvicorn_access_args() -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1", "GET", "/api/auth/callback?code=abc&state=xyz", "1.1", 302), None)
    assert RedactAccessQueryFilter().filter(record) is True
    assert "code=" not in record.getMessage()
    assert record.getMessage() == '127.0.0.1:1 - "GET /api/auth/callback HTTP/1.1" 302'


def test_filter_ignores_other_records() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    assert RedactAccessQueryFilter().filter(record) is True
    assert record.getMessage() == "hello world"
