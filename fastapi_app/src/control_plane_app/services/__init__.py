"""コントロールプレーンのサービス層（fastapi-domain 担当。FastAPI に依存しない）。

- ``tenant_provisioning`` — テナントの払い出し・再実行・停止・再開・削除要求・物理削除（:class:`TenantProvisioningService`）
- ``tenant_maintenance`` — 定期ジョブから呼ぶ保守処理（中断した払い出しの回収、物理削除の対象の抽出）
- ``tenant_lifecycle`` — 状態遷移の定義（01 §6.1）
- ``errors`` — 例外と HTTP ステータスの対応

本パッケージは re-export を行わない。各モジュールから明示的に import すること。
"""
