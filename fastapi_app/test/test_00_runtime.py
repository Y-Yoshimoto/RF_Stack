# -*- coding: utf-8 -*-
# ユニットテストコードサンプル
# https://docs.pytest.org/en/stable/getting-started.html
# from playwright.sync_api import Page
# ロギング設定
import logging
logger = logging.getLogger(__name__)
# 環境変数読み込み
import os
from dotenv import load_dotenv
load_dotenv()

class TestRuntime:
    """ Pytestの実行環境確認テスト"""

    def test_runtime(self, check):
        """ Pytestの実行環境確認テスト """
        logger.info("Pytestの動作環境を確認")
        with check:
            check.equal(1 + 1, 2, "1 + 1 は 2 ではありません")
            check.is_true(True, "Trueではありません")

    # def test_playwright(self, page: Page):
    #     """ Pytest-Playwrightの動作確認 """
    #     logger.info("Playwrightの動作環境を確認")
    #     page.goto("https://playwright.dev/python/")
    #     page.screenshot(path="./test/_tmp/screenshot.png")
    #     # Playwrightの文字列がページに表示されていることを確認
    #     count = page.locator("text=Playwright").count()
    #     assert count > 0, f"Playwrightの文字列がページに見つかりません (一致数: {count})"

    def test_conected_postgresql(self, check):
        """ PostgreSQLへの接続確認 Runtime DB への接続確認 """
        # 接続用モジュールのインポート
        from sqlmodel import Session, create_engine, text
        # DB接続情報を環境変数から取得(DB_USERは、Postgres用のデフォルト値を設定)
        DB_USER = os.getenv("DB_USER", "postgres")
        DB_PASSWORD = os.environ["POSTGRES_PASSWORD"]
        DB_HOST = os.environ["DB_HOST"]
        DB_PORT = os.environ["DB_PORT"]
        DB_NAME = "runtime_db"
        # URLを組み立ててDBエンジンを作成
        logger.info(f'PostgreSQLへの接続を確認: {DB_USER}:_password_@{DB_HOST}:{DB_PORT}/{DB_NAME}')
        engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}", echo=True)
        with Session(engine) as session:
            query = text("SELECT * FROM runtime_table;")
            logger.info(f'クエリを実行: {query}')
            result = session.exec(query)
            with check:
                assert result is not None, "PostgreSQLからデータが取得できません"
                assert list(result)[0][1] == "OK", "PostgreSQLから取得したデータの内容が不正です"
# 直接実行用
if __name__ == "__main__":
    test_instance = TestRuntime()
    test_instance.test_runtime()
