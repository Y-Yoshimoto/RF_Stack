# -*- coding: utf-8 -*-
"""modules.tenancy.rls(SQL 生成)と modules.tenancy.models(ヘルパー)のユニットテスト(DB 不要)。"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import Field, SQLModel

from modules.db_connector.metadata import create_plane_registry
from modules.tenancy import db as tenancy_db
from modules.tenancy import rls
from modules.tenancy.models import TENANT_ID_COLUMN, TenantScopedBase, TenantScopedMixin, tenant_scoped_fk, tenant_scoped_unique

PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


class TestQuoteIdentifier:
    """quote_identifier。"""

    @pytest.mark.parametrize(("name", "expected"), [("t_todo", '"t_todo"'), ("Mixed Case", '"Mixed Case"'), ('a"b', '"a""b"'), ('"', '""""'), ("日本語", '"日本語"')])
    def test_quotes_and_escapes(self, name, expected):
        """二重引用符で囲み、内部の二重引用符は 2 つにする。"""
        check.equal(rls.quote_identifier(name), expected)

    @pytest.mark.parametrize("name", ["", "a\x00b"])
    def test_rejects_empty_and_nul(self, name):
        """空文字と NUL 文字は ValueError。"""
        with pytest.raises(ValueError, match="invalid SQL identifier"):
            rls.quote_identifier(name)


class TestBuildEnableSql:
    """build_enable_tenant_rls_sql。"""

    def test_statements_and_order(self):
        """ENABLE → FORCE → CREATE POLICY の順で、ちょうど 3 文。"""
        statements = rls.build_enable_tenant_rls_sql("t_todo")
        check.equal(len(statements), 3)
        check.equal(statements[0], 'ALTER TABLE "public"."t_todo" ENABLE ROW LEVEL SECURITY')
        check.equal(statements[1], 'ALTER TABLE "public"."t_todo" FORCE ROW LEVEL SECURITY')
        check.is_true(statements[2].startswith('CREATE POLICY "tenant_isolation" ON "public"."t_todo" '))

    def test_policy_has_using_and_with_check_with_same_predicate(self):
        """USING と WITH CHECK の両方に同じ式(GUC 未設定なら NULL → 0 件)を設定する。"""
        policy = rls.build_enable_tenant_rls_sql("t_todo")[2]
        check.is_in(f"USING ({PREDICATE})", policy)
        check.is_in(f"WITH CHECK ({PREDICATE})", policy)
        check.equal(rls.TENANT_PREDICATE, PREDICATE)

    def test_schema_option(self):
        """schema を指定すると修飾し、None なら修飾しない。"""
        check.is_true(all('"app"."t"' in s for s in rls.build_enable_tenant_rls_sql("t", schema="app")))
        unqualified = rls.build_enable_tenant_rls_sql("t", schema=None)
        check.is_true(all(' "t"' in s and '"public"' not in s for s in unqualified))

    def test_identifiers_are_quoted_against_injection(self):
        """テーブル名・スキーマ名に引用符や SQL が含まれても識別子の中に閉じ込められる。"""
        evil = 'x"; DROP TABLE y; --'
        for statement in rls.build_enable_tenant_rls_sql(evil, schema='s"s') + rls.build_disable_tenant_rls_sql(evil, schema='s"s'):
            check.is_in('"s""s"."x""; DROP TABLE y; --"', statement)

    def test_invalid_identifier_raises(self):
        """空のテーブル名は ValueError。"""
        with pytest.raises(ValueError):
            rls.build_enable_tenant_rls_sql("")

    def test_disable_is_reverse(self):
        """無効化は DROP POLICY → NO FORCE → DISABLE の順。"""
        statements = rls.build_disable_tenant_rls_sql("t_todo")
        check.equal(
            statements,
            [
                'DROP POLICY "tenant_isolation" ON "public"."t_todo"',
                'ALTER TABLE "public"."t_todo" NO FORCE ROW LEVEL SECURITY',
                'ALTER TABLE "public"."t_todo" DISABLE ROW LEVEL SECURITY',
            ],
        )

    def test_guc_name_matches_db_module(self):
        """ポリシーが参照する GUC 名は db.py が設定する GUC 名と一致する(契約)。"""
        check.equal(rls.TENANT_GUC_NAME, tenancy_db.TENANT_GUC_NAME)
        check.is_in(f"'{tenancy_db.TENANT_GUC_NAME}'", rls.TENANT_PREDICATE)


class TestAlembicWrappers:
    """enable_tenant_rls / disable_tenant_rls は生成した文を順に op.execute へ渡す。"""

    def test_enable_executes_statements_in_order(self, monkeypatch):
        """enable_tenant_rls が build の結果を順に op.execute する。"""
        executed: list[str] = []
        monkeypatch.setattr("alembic.op.execute", executed.append, raising=False)
        rls.enable_tenant_rls("t_todo", schema="app")
        check.equal(executed, rls.build_enable_tenant_rls_sql("t_todo", schema="app"))

    def test_disable_executes_statements_in_order(self, monkeypatch):
        """disable_tenant_rls が build の結果を順に op.execute する。"""
        executed: list[str] = []
        monkeypatch.setattr("alembic.op.execute", executed.append, raising=False)
        rls.disable_tenant_rls("t_todo")
        check.equal(executed, rls.build_disable_tenant_rls_sql("t_todo"))


class TestModels:
    """modules.tenancy.models のヘルパー。"""

    def test_unique_constraint(self):
        """tenant_scoped_unique は (tenant_id, id) の UNIQUE 制約。"""
        constraint = tenant_scoped_unique()
        check.is_instance(constraint, UniqueConstraint)
        check.equal([c if isinstance(c, str) else c.name for c in constraint._pending_colargs], [TENANT_ID_COLUMN, "id"])

    def test_foreign_key_is_composite(self):
        """tenant_scoped_fk は (tenant_id, 列) → 参照先(tenant_id, id) の複合外部キー。"""
        fk = tenant_scoped_fk("created_by", "t_user", ondelete="CASCADE")
        check.is_instance(fk, ForeignKeyConstraint)
        check.equal(list(fk._pending_colargs), ["tenant_id", "created_by"])
        check.equal([e._colspec for e in fk.elements], ["t_user.tenant_id", "t_user.id"])
        check.equal(fk.ondelete, "CASCADE")

    def test_foreign_key_default_ondelete(self):
        """ondelete 未指定なら None。"""
        check.is_none(tenant_scoped_fk("created_by", "t_user").ondelete)

    def test_base_id_default_is_uuid7(self):
        """TenantScopedBase の id は UUIDv7 の主キーで、DB 側の既定値も uuidv7()。"""
        field = TenantScopedBase.model_fields["id"]
        generated = field.default_factory()
        check.is_instance(generated, uuid.UUID)
        check.equal(generated.version, 7)
        check.is_true(field.primary_key)
        check.equal(str(field.sa_column_kwargs["server_default"]), "uuidv7()")

    def test_tenant_id_is_required_not_null_and_indexed(self):
        """tenant_id は必須・NOT NULL・インデックス付きで、基底クラスは tenant_id と id を持つ。"""
        for model in (TenantScopedBase, TenantScopedMixin):
            field = model.model_fields["tenant_id"]
            check.is_true(field.is_required(), model.__name__)
            check.is_false(field.nullable, model.__name__)
            check.is_true(field.index, model.__name__)
        check.is_in("id", TenantScopedBase.model_fields)
        check.is_not_in("id", TenantScopedMixin.model_fields)

    def test_ddl_of_scoped_tables(self):
        """ヘルパーを使ったテーブルの DDL に、tenant_id の NOT NULL・複合 UNIQUE・複合 FK・uuidv7 既定値が出る(専用 registry で AP の MetaData を汚さない)。"""
        registry = create_plane_registry()

        class IsolatedBase(SQLModel, registry=registry):
            """テスト専用の基底(専用 MetaData)。"""

        class TParent(TenantScopedMixin, IsolatedBase, table=True):
            __tablename__ = "t_parent"
            __table_args__ = (tenant_scoped_unique(),)
            id: uuid.UUID = Field(default_factory=uuid.uuid7, primary_key=True)

        class TChild(TenantScopedMixin, IsolatedBase, table=True):
            __tablename__ = "t_child"
            __table_args__ = (tenant_scoped_fk("parent_id", "t_parent"),)
            id: uuid.UUID = Field(default_factory=uuid.uuid7, primary_key=True)
            parent_id: uuid.UUID

        parent_ddl = str(CreateTable(TParent.__table__).compile(dialect=postgresql.dialect()))
        child_ddl = str(CreateTable(TChild.__table__).compile(dialect=postgresql.dialect()))
        check.is_in("tenant_id UUID NOT NULL", parent_ddl)
        check.is_in("CONSTRAINT t_parent_tenant_id_id_key UNIQUE (tenant_id, id)", parent_ddl)
        check.is_in("CONSTRAINT t_child_tenant_id_parent_id_fkey FOREIGN KEY(tenant_id, parent_id) REFERENCES t_parent (tenant_id, id)", child_ddl)
        check.is_in("ix_t_parent_tenant_id", [i.name for i in TParent.__table__.indexes])
        check.equal(sorted(registry.metadata.tables), ["t_child", "t_parent"])
