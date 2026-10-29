# -*- coding: utf-8 -*-
"""modules.tenancy.tenant_code(テナントコードの形式と予約語。01 §5.1 / §5.2)のテスト。"""
import re

import pytest
import pytest_check as check

from modules.tenancy.tenant_code import (
    RESERVED_TENANT_CODES,
    InvalidTenantCodeFormatError,
    TenantCodeViolation,
    is_reserved_tenant_code,
    tenant_code_violation,
    validate_tenant_code,
)

# 01 §5.2 に書かれている予約語(実装の定数とは別に、仕様書の記載をそのまま転記したもの)
SPEC_RESERVED_WORDS = {
    "cp", "api", "auth", "login", "logout", "callback", "dev-login", "link",
    "assets", "static", "public", "health", "admin", "keycloak",
    "www", "app", "docs", "help", "support", "status", "signup", "settings",
}


class TestFormatAccepted:
    """形式に合うテナントコード。"""

    @pytest.mark.parametrize(
        "code",
        [
            "abc",  # 最短の 3 文字
            "a" * 32,  # 最長の 32 文字
            "a1b",
            "123",  # 数字だけ
            "0ab",
            "a-b",  # 内部の単独ハイフン
            "abc-def-ghi",
            "a" + "-b" * 15 + "c",  # 32 文字でハイフンを多用
            "alpha",
            "beta",
        ],
    )
    def test_valid(self, code):
        """3〜32 文字の英小文字・数字・内部の単独ハイフンは受理され、そのまま返る(正規化しない)。"""
        check.is_none(tenant_code_violation(code))
        check.equal(validate_tenant_code(code), code)


class TestFormatRejected:
    """形式に合わないテナントコード(理由は FORMAT)。"""

    @pytest.mark.parametrize(
        "code",
        [
            "",  # 空
            "a",
            "ab",  # 2 文字(下限未満)
            "a" * 33,  # 33 文字(上限超過)
            "-abc",  # 先頭ハイフン
            "abc-",  # 末尾ハイフン
            "a--b",  # 連続ハイフン
            "abc--",
            "---",
            "ABC",  # 大文字
            "Abc",
            "ab_c",  # アンダースコア
            "ab.c",  # ドット
            "ab c",  # 空白
            " abc",
            "abc ",
            "abc\n",  # 末尾の改行($ だけだと通ってしまう)
            "\nabc",
            "abc\r\n",
            "ab\nc",
            "abc\x00",
            "日本語",
            "ａｂｃ",  # 全角英字
            "abc/def",
            "../abc",
        ],
    )
    def test_invalid(self, code):
        """境界値・改行・連続ハイフン・非 ASCII などは形式違反(FORMAT)。"""
        check.equal(tenant_code_violation(code), TenantCodeViolation.FORMAT)
        with pytest.raises(InvalidTenantCodeFormatError) as exc_info:
            validate_tenant_code(code)
        check.equal(exc_info.value.violation, TenantCodeViolation.FORMAT)

    @pytest.mark.parametrize("value", [None, 123, b"abc", ["abc"], object()])
    def test_non_string_is_format_violation(self, value):
        """文字列以外(外部入力の型違い)は例外にならず形式違反として扱う。"""
        check.equal(tenant_code_violation(value), TenantCodeViolation.FORMAT)
        with pytest.raises(InvalidTenantCodeFormatError):
            validate_tenant_code(value)

    def test_error_message_does_not_contain_input(self):
        """例外メッセージに入力値そのものを含めない(ログへ外部入力をそのまま出さない)。"""
        with pytest.raises(InvalidTenantCodeFormatError) as exc_info:
            validate_tenant_code("Evil\nInput")
        check.is_not_in("Evil", str(exc_info.value))
        check.is_in("format", str(exc_info.value))


class TestReserved:
    """予約語(理由は RESERVED)。"""

    def test_reserved_list_matches_spec(self):
        """予約語の一覧は 01 §5.2 の記載と過不足なく一致する。"""
        check.equal(set(RESERVED_TENANT_CODES), SPEC_RESERVED_WORDS)

    @pytest.mark.parametrize("word", sorted(w for w in SPEC_RESERVED_WORDS if re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}", w)))
    def test_reserved_words_that_fit_the_format(self, word):
        """形式に合う予約語(admin, dev-login など)は RESERVED として拒否される。"""
        check.equal(tenant_code_violation(word), TenantCodeViolation.RESERVED)
        with pytest.raises(InvalidTenantCodeFormatError) as exc_info:
            validate_tenant_code(word)
        check.equal(exc_info.value.violation, TenantCodeViolation.RESERVED)

    def test_cp_is_rejected_by_format_first(self):
        """2 文字の ``cp`` は形式違反が先に判定される(予約語の一覧には含まれる)。"""
        check.is_in("cp", RESERVED_TENANT_CODES)
        check.equal(tenant_code_violation("cp"), TenantCodeViolation.FORMAT)

    @pytest.mark.parametrize("word", ["admin", "ADMIN", "Admin", "dev-login", "DEV-LOGIN"])
    def test_is_reserved_ignores_case(self, word):
        """予約語の判定単体は大文字小文字を区別しない。"""
        check.is_true(is_reserved_tenant_code(word))

    @pytest.mark.parametrize("word", ["ADMIN", "Admin"])
    def test_uppercase_reserved_word_is_a_format_violation(self, word):
        """大文字の予約語は正規化せず、形式違反として拒否される。"""
        check.equal(tenant_code_violation(word), TenantCodeViolation.FORMAT)

    @pytest.mark.parametrize("code", ["administrator", "api-v2", "my-admin", "admin1", "alpha", "beta"])
    def test_words_containing_reserved_words_are_allowed(self, code):
        """予約語を含むだけの文字列や既存テナント(alpha / beta)は予約語ではない。"""
        check.is_false(is_reserved_tenant_code(code))
        check.is_none(tenant_code_violation(code))
