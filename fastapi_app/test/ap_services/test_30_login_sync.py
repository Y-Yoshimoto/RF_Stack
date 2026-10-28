# -*- coding: utf-8 -*-
"""main_app.route.auth.login_sync(ログイン完了時の AP のユーザー同期の呼び出し)を、実際の DB で確認するテスト。

``test/auth`` のテストは同期処理を差し替えて呼び出しの順序・失敗時の扱いを確認している。ここでは差し替えずに、
``app_runtime`` のセッションとテナントコンテキストを実際に通して、ユーザー行・デフォルト組織が作られることを確認する。
テナントは使い捨て(ランダムな UUID)。alpha / beta には触れない。
"""
import uuid

import pytest
import pytest_check as check

from main_app.route.auth import login_sync
from main_app.services.errors import UserDeactivatedError
from modules.tenancy import providers
from modules.tenancy.context import get_tenant_context


@pytest.fixture(autouse=True)
def _dispose_providers():
    """providers のエンジン・sessionmaker はテストごとに破棄する(接続を残さない)。"""
    yield
    providers.dispose_providers()


def session_data(sub: str, **user) -> dict:
    base = {"sub": sub, "preferred_username": "taro", "name": "Taro Yamada", "email": "taro@example.com"}
    base.update(user)
    return {"plane": "app", "realm": "tenant-x", "tenant_code": "x", "user": {k: v for k, v in base.items() if v is not None}}


def sync(ap_db, ctx, data):
    return login_sync.sync_app_user_on_login(data, tenant_id=ctx.tenant_id, tenant_code=ctx.tenant_code)


def test_first_login_creates_user_and_default_organization(ap_db):
    """実 DB で、初回ログインがユーザー行(sub・メール・name クレームの表示名)とデフォルト組織を作り、終了後はテナントコンテキストを戻す。"""
    ctx = ap_db.tenant()
    sub = str(uuid.uuid4())
    result = sync(ap_db, ctx, session_data(sub))
    check.is_true(result.created)
    check.is_not_none(result.default_organization_id)
    row = ap_db.user(ctx, result.user_id)
    check.equal((row["idp_subject"], row["email"], row["display_name"], row["tenant_id"]), (sub, "taro@example.com", "Taro Yamada", ctx.tenant_id))
    check.equal(len(ap_db.orgs(ctx)), 1)
    check.is_none(get_tenant_context())


def test_name_claim_wins_over_preferred_username(ap_db):
    """表示名は name クレームを使い、preferred_username では上書きしない。name が無い場合だけ preferred_username、どちらも無ければメールになる。"""
    ctx = ap_db.tenant()
    sub = str(uuid.uuid4())
    first = sync(ap_db, ctx, session_data(sub))
    check.equal(ap_db.user(ctx, first.user_id)["display_name"], "Taro Yamada")
    sync(ap_db, ctx, session_data(sub, name=None))
    check.equal(ap_db.user(ctx, first.user_id)["display_name"], "taro")
    sync(ap_db, ctx, session_data(sub, name=None, preferred_username=None))
    check.equal(ap_db.user(ctx, first.user_id)["display_name"], "taro@example.com")


def test_second_login_keeps_version_and_updates_last_login(ap_db):
    """2 回目のログイン(プロフィール同じ)は version を上げず、last_login_at だけを進める。デフォルト組織は増えない。"""
    ctx = ap_db.tenant()
    sub = str(uuid.uuid4())
    first = sync(ap_db, ctx, session_data(sub))
    before = ap_db.user(ctx, first.user_id)
    second = sync(ap_db, ctx, session_data(sub))
    after = ap_db.user(ctx, first.user_id)
    check.equal((second.created, second.profile_updated, after["version"]), (False, False, 1))
    check.greater(after["last_login_at"], before["last_login_at"])
    check.equal(len(ap_db.orgs(ctx)), 1)


def test_non_uuid_subject_works(ap_db):
    """sub が UUID でなくても(コンテキストの user_id は None になるが)同期できる。"""
    ctx = ap_db.tenant()
    result = sync(ap_db, ctx, session_data("not-a-uuid-subject"))
    check.equal(ap_db.user(ctx, result.user_id)["idp_subject"], "not-a-uuid-subject")


def test_deactivated_user_is_rejected_and_context_is_restored(ap_db):
    """無効化されたユーザーは UserDeactivatedError。行は変わらず、デフォルト組織も作らず、コンテキストは戻る。"""
    ctx = ap_db.tenant()
    sub = str(uuid.uuid4())
    user = ap_db.add_user(ctx, sub=sub, email="old@example.com", display_name="Old", is_active=False)
    with pytest.raises(UserDeactivatedError):
        sync(ap_db, ctx, session_data(sub))
    row = ap_db.user(ctx, user.id)
    check.equal((row["email"], row["display_name"], row["version"], row["last_login_at"]), ("old@example.com", "Old", 1, None))
    check.equal(ap_db.orgs(ctx), [])
    check.is_none(get_tenant_context())


def test_two_tenants_do_not_share_rows(ap_db):
    """同じ sub が 2 つのテナントにログインしても、それぞれのテナントに別のユーザー行・デフォルト組織が作られる(テナントはレジストリ確認済みの引数だけで決まる)。"""
    a, b = ap_db.tenant(), ap_db.tenant()
    sub = str(uuid.uuid4())
    ra, rb = sync(ap_db, a, session_data(sub)), sync(ap_db, b, session_data(sub))
    check.not_equal(ra.user_id, rb.user_id)
    check.equal([u["tenant_id"] for u in ap_db.users(a)], [a.tenant_id])
    check.equal([u["tenant_id"] for u in ap_db.users(b)], [b.tenant_id])
    check.equal((len(ap_db.orgs(a)), len(ap_db.orgs(b))), (1, 1))
    check.not_equal(ap_db.orgs(a)[0]["id"], ap_db.orgs(b)[0]["id"])


def test_token_claim_tenant_id_cannot_redirect_the_write(ap_db):
    """セッションのユーザー情報に別テナントの tenant_id が入っていても無視され、引数(レジストリで確認済み)のテナントにだけ書く。"""
    a, b = ap_db.tenant(), ap_db.tenant()
    data = session_data(str(uuid.uuid4()), tenant_id=str(b.tenant_id))
    data["tenant_id"] = str(b.tenant_id)
    result = sync(ap_db, a, data)
    check.equal([u["id"] for u in ap_db.users(a)], [result.user_id])
    check.equal(ap_db.users(b), [])
    check.equal(ap_db.orgs(b), [])
