#!/bin/bash
## 一時ファイルを一括削除するスクリプト
DIR=./react_app/
DIR=${1:-./react_app/}
echo "Cleaning temporary files in '${DIR}'."

# Eslintの一時ファイルを削除する
rm -rf ${DIR}eslint-report.html

# Viteのビルド時に生成される一時ファイルを削除する
rm -rf ${DIR}dist
rm -rf ${DIR}dev-dist

# Vitestのテスト時に生成される一時ファイルを削除する
rm -rf ${DIR}coverage
find . -type d -name "__screenshots__" -exec rm -rf {} +

# Playwrightのテスト時に生成される一時ファイルを削除する
rm -rf ${DIR}test-results
rm -rf ${DIR}playwright-report
rm -f ${DIR}test-results.json
rm -f ${DIR}test-results.xml
rm -f ${DIR}rollup-visualizer.html
rm -f ${DIR}madge_graph.svg
