#!/usr/bin/env python
# coding:utf-8
""" テナント分離の行レベルセキュリティ(RLS)を設定する Alembic 用ヘルパー

    アプリケーションプレーン DB のテナントスコープ・テーブルに、以下の契約で RLS を設定する。

    - GUC: `app.current_tenant`(`modules.tenancy.db` がトランザクション単位で設定する)
    - ポリシー名: `tenant_isolation`
    - USING / WITH CHECK: `tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid`
      GUC が未設定または空文字の場合は NULL との比較になり、エラーにならず 0 件になる。
    - `ENABLE` と `FORCE ROW LEVEL SECURITY` の両方を設定し、テーブル所有者(app_owner)にも適用する。

    SQL 文を返す純粋関数(`build_*`)と、Alembic の `op.execute` で実行するラッパーを分けている。

    使い方(alembic/app/versions/ のリビジョン):
        from modules.tenancy.rls import disable_tenant_rls, enable_tenant_rls

        def upgrade() -> None:
            op.create_table("t_todo", ...)
            enable_tenant_rls("t_todo")

        def downgrade() -> None:
            disable_tenant_rls("t_todo")
            op.drop_table("t_todo")
"""
TENANT_GUC_NAME = "app.current_tenant"
TENANT_POLICY_NAME = "tenant_isolation"
TENANT_PREDICATE = f"tenant_id = NULLIF(current_setting('{TENANT_GUC_NAME}', true), '')::uuid"


def quote_identifier(name: str) -> str:
    """
        PostgreSQL の識別子として二重引用符でクォートする
        name: 識別子(空文字・NUL 文字は不可)
        return: クォート済みの識別子
    """
    if not name or "\x00" in name:
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def _qualified_table(table_name: str, schema: str | None) -> str:
    """ スキーマ修飾したテーブル名を返す """
    table = quote_identifier(table_name)
    return f"{quote_identifier(schema)}.{table}" if schema else table


def build_enable_tenant_rls_sql(table_name: str, *, schema: str | None = "public") -> list[str]:
    """
        テナント分離の RLS を有効化する SQL 文を返す(実行順)
        table_name: テーブル名
        schema: スキーマ名(None の場合は修飾しない)
        return: SQL 文のリスト
    """
    table = _qualified_table(table_name, schema)
    policy = quote_identifier(TENANT_POLICY_NAME)
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {policy} ON {table} USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})",
    ]


def build_disable_tenant_rls_sql(table_name: str, *, schema: str | None = "public") -> list[str]:
    """
        `build_enable_tenant_rls_sql` の逆操作の SQL 文を返す(実行順)
        table_name: テーブル名
        schema: スキーマ名(None の場合は修飾しない)
        return: SQL 文のリスト
    """
    table = _qualified_table(table_name, schema)
    policy = quote_identifier(TENANT_POLICY_NAME)
    return [
        f"DROP POLICY {policy} ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]


def enable_tenant_rls(table_name: str, *, schema: str | None = "public") -> None:
    """ Alembic のマイグレーション内で、テナント分離の RLS を有効化する """
    from alembic import op

    for statement in build_enable_tenant_rls_sql(table_name, schema=schema):
        op.execute(statement)


def disable_tenant_rls(table_name: str, *, schema: str | None = "public") -> None:
    """ Alembic のマイグレーション内で、テナント分離の RLS を無効化する """
    from alembic import op

    for statement in build_disable_tenant_rls_sql(table_name, schema=schema):
        op.execute(statement)
