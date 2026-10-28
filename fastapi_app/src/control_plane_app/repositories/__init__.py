"""コントロールプレーンのリポジトリ層（DB アクセス。コミットはサービス層が行う）。

- ``tenant_repository`` — CP DB のテナント台帳・払い出し履歴・CP 監査ログ（``cp_runtime``）
- ``app_tenant_data`` — AP DB のテナントデータの物理削除（``app_cp_agent``、RLS 適用。01 §13 #9 の拡張点）
- ``app_tenant_metrics`` — AP DB のテナント毎のメトリクスの集計（``app_cp_agent``、RLS 適用。01 §6.4）
- ``daily_metric_repository`` — CP DB の日次メトリクス（``t_tenant_daily_metric``）の UPSERT
- ``locks`` — CP DB の advisory lock による排他（テナント単位の操作、定期ジョブ）
"""
