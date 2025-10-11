# -*- coding: utf-8 -*-
# ユニットテストコードサンプル
# https://docs.pytest.org/en/stable/getting-started.html
import pytest
import pytest_check as check
from playwright.sync_api import Page
import logging
logger = logging.getLogger(__name__)

class TestRuntime:
    """ Pytestの実行環境確認テスト"""

    def test_runtime(self):
        """ Pytestの動作確認
            アサーションを実行して、Pytestが正しく動作していることを確認"""
        logger.info("Pytestの動作環境を確認")
        check.equal(1 + 1, 2, "1 + 1 は 2 ではありません")
        check.is_true(True, "Trueではありません")

    def test_playwright(self, page: Page):
        """ Playwrightの動作確認
            Playwrightのページにアクセスし、スクリーンショットを取得
        """
        logger.info("Playwrightの動作環境を確認")
        page.goto("https://playwright.dev/python/")
        page.screenshot(path="./test/_tmp/screenshot.png")
        # Playwrightの文字列がページに表示されていることを確認
        count = page.locator("text=Playwright").count()
        assert count > 0, f"Playwrightの文字列がページに見つかりません (一致数: {count})"

        

# 直接実行用
if __name__ == "__main__":
    test_instance = TestRuntime()
    test_instance.test_runtime()
