# -*- coding: utf-8 -*-
"""modules.tenancy.db のユニットテスト(DB 不要。接続をモックして SQL とパラメータを検証)。"""
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_check as check
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from modules.tenancy import db
from modules.tenancy.context import TenantContext, tenant_scope


def _connection() -> MagicMock:
    return MagicMock(spec=Connection)


class TestApplyTenantGuc:
    """apply_tenant_guc。"""

    def test_sets_uuid_as_bind_parameter_with_local_scope(self):
        """テナント ID はバインドパラメータで渡し、SQL は is_local=true の set_config。"""
        connection = _connection()
        tenant_id = uuid.uuid4()
        db.apply_tenant_guc(connection, tenant_id)
        statement, params = connection.execute.call_args.args
        check.equal(params, {"tenant_id": str(tenant_id)})
        sql = str(statement)
        check.is_in("set_config('app.current_tenant', :tenant_id, true)", sql)
        check.is_not_in(str(tenant_id), sql, "値を SQL 文字列に埋め込まない")

    def test_none_sets_empty_string(self):
        """None は空文字を設定する(RLS では 0 件になる状態)。"""
        connection = _connection()
        db.apply_tenant_guc(connection, None)
        check.equal(connection.execute.call_args.args[1], {"tenant_id": ""})

    @pytest.mark.parametrize("bad", ["8d2f2d54-0000-7000-8000-000000000000", 1, b"x"])
    def test_rejects_non_uuid(self, bad):
        """UUID / None 以外は TypeError で、SQL は実行しない。"""
        connection = _connection()
        with pytest.raises(TypeError):
            db.apply_tenant_guc(connection, bad)
        connection.execute.assert_not_called()

    def test_session_uses_connection(self):
        """Session の場合は session.connection() 経由で実行する。"""
        session = MagicMock(spec=Session)
        db.apply_tenant_guc(session, uuid.uuid4())
        session.connection.assert_called_once()
        session.connection.return_value.execute.assert_called_once()


class TestTenantGucScopeArguments:
    """tenant_guc_scope / run_per_tenant の引数検証。"""

    def test_scope_rejects_non_uuid_before_touching_db(self):
        """UUID 以外は TypeError で、DB へは何も送らない。"""
        connection = _connection()
        with pytest.raises(TypeError):
            with db.tenant_guc_scope(connection, "not-uuid"):  # type: ignore[arg-type]
                pass
        connection.execute.assert_not_called()

    def test_run_per_tenant_with_no_tenants_returns_empty(self):
        """テナントが 0 件なら何も実行せず空の辞書。"""
        connection = _connection()
        check.equal(db.run_per_tenant(connection, [], lambda _tid: 1), {})
        connection.execute.assert_not_called()


class TestListenerRegistration:
    """install / uninstall の登録管理(イベントはセッションを開始しない限り発火しない)。"""

    def test_install_is_idempotent_and_uninstall_removes(self):
        """重複登録は無視され、解除できる。未登録の解除は何もしない。"""
        from sqlalchemy import event

        factory = sessionmaker()
        db.uninstall_tenant_guc_listener(factory)  # 未登録でも例外なし
        db.install_tenant_guc_listener(factory)
        db.install_tenant_guc_listener(factory)
        check.is_true(event.contains(factory, "after_begin", db._apply_context_tenant_on_begin))
        db.uninstall_tenant_guc_listener(factory)
        check.is_false(event.contains(factory, "after_begin", db._apply_context_tenant_on_begin))

    def test_listener_does_nothing_without_context(self):
        """コンテキストが無ければ GUC を設定しない。"""
        connection = _connection()
        db._apply_context_tenant_on_begin(MagicMock(), MagicMock(), connection)
        connection.execute.assert_not_called()

    def test_listener_applies_context_tenant(self):
        """コンテキストがあれば、そのテナント ID を設定する。"""
        connection = _connection()
        ctx = TenantContext(tenant_id=uuid.uuid4(), tenant_code="alpha")
        with tenant_scope(ctx):
            db._apply_context_tenant_on_begin(MagicMock(), MagicMock(), connection)
        check.equal(connection.execute.call_args.args[1], {"tenant_id": str(ctx.tenant_id)})
