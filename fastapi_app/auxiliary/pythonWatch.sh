#!/bin/bash

# 引数が指定されていない場合はエラーメッセージを表示して終了
if [ $# -eq 0 ]; then
    echo "Usage: $0 <file>"
    exit 1
fi

# 引数で指定されたファイルを監視して、保存されたらPythonスクリプトを実行
echo "---" python $1 "---------------"
python "$1"
while inotifywait -qq -e close_write --include '\.py$' -r .; do
    echo "---" python $1 "---------------"
    python "$1"
    echo "-------------------------------"
done