# 概要

React/TypeScript/Vite で Material-UI を使うサンプルリポジトリ  
devcontainer を使って開発することを想定した構成
動作確認用の Nnginx コンテナも同梱

## 初期設定

1. git クローン
   `git clone`

2. 環境変数ファイルを作成(自身の UID/GID を設定する)
   `./generateEnvfile.sh`

3. devcontainer を起動
   .npm.lock ファイルがある場合は、npm install が実行中のためインストールが完了するまで待つ

<https://github.com/mui/material-ui/tree/master/examples/material-ui-vite-ts>

## Chrome 拡張機能

- [React Developer Tools](https://ja.react.dev/learn/react-developer-tools)
  StrictModeでコンソールが2回出力されるため、拡張機能で表示の抑止をすることができる。
