-- Postgresqlの初期化時に生成される関数群

-- 管理用データベースに接続
\c {{CONTROL_PLANE_DB_NAME}}

-- updated_atカラムを自動更新するトリガー関数
-- 参考: https://pgsql-jp.github.io/current/html/plpgsql-trigger.html
CREATE FUNCTION fun_update_at() RETURNS OPAQUE AS '
    begin
        new.updated_at := ''now'';
        return new;
    end;
' LANGUAGE plpgsql;
-- テーブル作成時にトリガーを設定する例
-- DB負荷を考慮して、アプリケーション側で更新するようにするため、関数の設定のみ
-- CREATE TRIGGER tri_update_at BEFORE UPDATE ON sample FOR EACH ROW EXECUTE PROCEDURE fun_update_at();

