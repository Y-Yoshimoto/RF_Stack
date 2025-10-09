# conftest.py
# pytest設定ファイル
import pytest
# テスト用のロガー設定
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# テスト用の環境変数読み込み
import os
from dotenv import dotenv_values
""" 
    pytest-envを使用する方法もあるが、秘匿情報を含むため、.envファイルを使用して環境変数を読み込む
""" 


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """ pytestの実行前に環境変数を読み込むフック """
    config.env = dotenv_values('.env')
    print("============================= environment variables ============================")
    # config.envの中身をkeyとvalueのペアで表示
    for key, value in config.env.items():
        print(f"{key}={value}")

# レポート設定関連
# https://pytest-html.readthedocs.io/en/latest/index.html
## pytestのHTMLレポートのタイトルを設定
@pytest.hookimpl(tryfirst=True)
def pytest_html_report_title(report):
    """ HTMLレポートのタイトルを設定 """
    report.title = 'Pytest レポート'

# HTMLレポートのヘッダーにカスタム情報を追加
@pytest.hookimpl(tryfirst=True)
def pytest_html_results_table_header(cells):
    """ HTMLレポートのヘッダーにpydocからの説明列を追加 """
    cells.insert(1, "<th>Description</th>")
@pytest.hookimpl(tryfirst=True)
def pytest_html_results_table_row(report, cells):
    """ HTMLレポートの各行にpydocからの説明列を追加 """
    cells.insert(1, f'<td>{report.description}</td>')
## HTMLレポートのテスト結果の詳細にカスタム情報を追加
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """ テスト結果の詳細にpydocからの説明を追加 """
    outcome = yield
    report = outcome.get_result()
    report.description = str(item.function.__doc__)
