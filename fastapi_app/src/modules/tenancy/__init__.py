"""マルチテナントのテナント分離を担う共通部品。

プール型マルチテナント構成で、アプリケーションプレーン DB ``app_db`` の全テーブルを
``tenant_id`` と PostgreSQL RLS で分離するための部品をまとめる。RLS ポリシーは GUC
``app.current_tenant`` を参照し、未設定なら 0 件となる。

テナントコンテキストは常に認証済みセッションから導出し、リクエストボディやクエリの
``tenant_id`` は信用しない。

モジュール構成:
    - ``context``    — :class:`TenantContext` と ``contextvars`` による保持（フレームワーク非依存）。
    - ``registry``   — 有効テナント一覧（``v_tenant_registry``）の読み取りインターフェースと
      TTL キャッシュ（AP からコントロールプレーンへの唯一の依存口）。
    - ``resolver``   — 認証済みユーザー情報とレジストリからテナントコンテキストを導出する判定ロジック
      （フレームワーク非依存）。
    - ``db``         — GUC ``app.current_tenant`` をトランザクションに適用する（SQLAlchemy 依存）。
      コントロールプレーンがテナントを切り替えながら集計・削除するための部品も含む。
    - ``dependency`` — リクエスト中だけテナントコンテキストを設定する FastAPI 依存関数のファクトリ。
    - ``models``     — テナント分離に関わるテーブル定義（postgres-schema 担当）。
    - ``rls``        — RLS ポリシーの定義・適用（postgres-schema 担当）。

本パッケージは re-export を行わない。各モジュールから明示的に import すること::

    from modules.tenancy.context import require_tenant_context
"""
