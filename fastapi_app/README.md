# FastAPIを使用したWebAPIプロキシ

## FastAPI_v3ベース

## 概要
WebAPIのテストを行うためのサンプルコード
FastAPIはテスト対象のWebAPIを模倣しテストコードを書くために使用する。

## 起動
VScodeの実行機能を使用して起動

## ショートカットコマンド
py: pythonコマンド
pyw: ホットリロード
pytest: pytestコマンド

## データベース
### 接続先情報
export PGPASSWORD=postgres
psql -h postgres_c -p 5432 -U postgres
psql -h postgres_c -p 5432 -U postgres -d sampledb

## 参考

- [FastAPI](https://fastapi.tiangolo.com/)
- [Strawberry](https://strawberry.rocks)
- [FastAPI + Strawberry](https://fastapi.tiangolo.com/how-to/graphql/)
- [Psycopg3](https://www.psycopg.org/)
