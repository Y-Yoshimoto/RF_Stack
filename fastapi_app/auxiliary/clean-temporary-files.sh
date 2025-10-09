#!/bin/bash -x
## 一時ファイルを一括削除するスクリプト
DIR=./fastapi_app/
DIR=${1:-./fastapi_app/}
echo "Cleaning temporary files in '${DIR}'."

# 一時ファイルを削除する
rm -rf ${DIR}.pytest_cache
rm -rf ${DIR}pytest_report.html
rm -f ${DIR}.coverage
rm -rf ${DIR}.ruff_cache
