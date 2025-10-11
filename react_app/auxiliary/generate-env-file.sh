# ../.env 環境変数ファイルを生成するスクリプト
# このスクリプトは、../.env.default ファイルをコピーして、../.env ファイルを生成します。
# 既に ../.env ファイルが存在する場合は、上書きせずに終了します。
# force オプションを指定すると、既存の ../.env ファイルを上書きします。
if [ "$1" = "--force" ]; then
    cp -p ../.env.default ../.env
    echo "既存の ../.env ファイルを上書きします"
elif [ ! -e ../.env ]; then
    cp -p ../.env.default ../.env
else
    echo ".env ファイルは既に存在します" >&2
    exit 1
fi
# ユーザーID, グループIDを取得して ../.env ファイルに設定する
echo 'USER_ID='$(id -u) >> ../.env
echo 'GROUP_ID='$(id -g) >> ../.env


echo "環境変数ファイルを生成しました。"