-- Postgresql　初期データ投入サンプル
-- 開発環境の動作確認用データの追加

-- 開発環境の動作確認用データベースの作成
CREATE DATABASE runtime_db;
-- データベースの切り替え
\c runtime_db
-- テーブルの作成
CREATE TABLE runtime_table (
    id SERIAL PRIMARY KEY,
    description VARCHAR(255)
);
-- データの投入
INSERT INTO runtime_table (description) VALUES ('OK');
-- テーブルのデータを取得
SELECT * FROM runtime_table;

