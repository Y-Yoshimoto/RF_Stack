# PostgreSQL

## 設定ファイル

## Mac用クライアントのインストール

Homebrewをインストールし、以下のコマンドでインストールする。
    ``brew install postgresql``

## 接続

psql -U postgres -h postgres_c -p 5432
ポート番号は環境に合わせて指定

### 基本操作

### 管理

## コンテナ関連

- 設定ファイルコピー先
- バックアップデータ:

## 公式Dockerファイル

    [Docker Hub](https://hub.docker.com/_/postgres)

## 基本的な操作コマンド

### データベース操作

- データベース一覧表示
    \l
- データベース作成
    CREATE DATABASE dbname;
- データベース削除
    DROP DATABASE dbname;
- データベース接続
    \c dbname;
- テーブル一覧表示
    \dt
- テーブル作成
    CREATE TABLE tablename (columnname datatype);
- テーブル削除
    DROP TABLE tablename;
- テーブル構造表示
    \d tablename;
- テーブルデータ表示
    SELECT * FROM tablename;
- テーブルデータ挿入
    INSERT INTO tablename VALUES (value1, value2, ...);
- テーブルデータ更新
    UPDATE tablename SET columnname = value WHERE condition;
