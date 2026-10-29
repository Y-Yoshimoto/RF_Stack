# -*- coding: utf-8 -*-
"""main_app.route.auth.login_sync(AP のログイン完了時のユーザー同期の呼び出し)のテスト。

DB には接続しない。``open_app_session`` と ``sync_user_on_login`` を差し替え、テナントコンテキストと引数の受け渡しを確認する。
``sync_user_on_login`` 自体の振る舞いは services のテストで確認する。
"""
import uuid
from contextlib import contextmanager

import pytest
import pytest_check as check

from main_app.route.auth import login_sync
from main_app.services.errors import UserDeactivatedError
from main_app.services.user_sync import UserSyncResult
from modules.tenancy.context import get_tenant_context

TENANT_ID = uuid.UUID("0194e6a0-0000-7000-8000-00000000a1fa")
SUB = "5f0c2b8e-7d1a-4c3e-9b2a-0123456789ab"


def _session_data(**user) -> dict:
    base = {"sub": SUB, "preferred_username": "alpha-member1", "name": "Taro Yamada", "email": "member1@alpha.example.com"}
    base.update(user)
    return {"plane": "app", "realm": "tenant-alpha", "tenant_code": "alpha", "user": {k: v for k, v in base.items() if v is not None}}


@pytest.fixture
def recorded(monkeypatch) -> dict:
    """AP のセッションと同期処理を差し替え、呼び出し時のテナントコンテキストと引数を記録する。"""
    state: dict = {"opened": [], "calls": [], "error": None}

    @contextmanager
    def fake_open():
        state["opened"].append(get_tenant_context())
        yield "app-session"

    def fake_sync(session, *, tenant_id, idp_subject, email, display_name, first_name=None, last_name=None, roles=None):
        state["calls"].append({"session": session, "ctx": get_tenant_context(), "tenant_id": tenant_id, "idp_subject": idp_subject, "email": email, "display_name": display_name})
        if state["error"] is not None:
            raise state["error"]
        return UserSyncResult(user_id=uuid.uuid4(), created=True, profile_updated=False, email_conflict=False, default_organization_id=None)

    monkeypatch.setattr(login_sync, "open_app_session", fake_open)
    monkeypatch.setattr(login_sync, "sync_user_on_login", fake_sync)
    return state


def test_syncs_in_the_tenant_context(recorded):
    """テナントのコンテキスト (plane=app) で AP のセッションを開き、セッションのユーザーで同期する。終了後はコンテキストを戻す。"""
    login_sync.sync_app_user_on_login(_session_data(), tenant_id=TENANT_ID, tenant_code="alpha")
    call = recorded["calls"][0]
    ctx = call["ctx"]
    check.equal((ctx.tenant_id, ctx.tenant_code, ctx.plane, ctx.user_id), (TENANT_ID, "alpha", "app", uuid.UUID(SUB)))
    check.equal(recorded["opened"][0], ctx, "セッションもテナントのコンテキストで開く")
    check.equal((call["session"], call["tenant_id"], call["idp_subject"], call["email"]), ("app-session", TENANT_ID, SUB, "member1@alpha.example.com"))
    check.is_none(get_tenant_context())


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ({}, "Taro Yamada"),
        ({"name": None}, "alpha-member1"),
        ({"name": "  "}, "alpha-member1"),
        ({"name": None, "preferred_username": None}, None),
    ],
    ids=["name", "no-name", "blank-name", "neither"],
)
def test_display_name_prefers_name_claim(recorded, user, expected):
    """表示名は name クレーム、無ければ preferred_username (UserService が作る表示名を上書きしない)。"""
    login_sync.sync_app_user_on_login(_session_data(**user), tenant_id=TENANT_ID, tenant_code="alpha")
    check.equal(recorded["calls"][0]["display_name"], expected)


def test_non_uuid_subject_is_not_set_as_context_user(recorded):
    """sub が UUID でなければ、コンテキストの user_id は None (同期の idp_subject はそのまま)。"""
    login_sync.sync_app_user_on_login(_session_data(sub="not-a-uuid"), tenant_id=TENANT_ID, tenant_code="alpha")
    check.is_none(recorded["calls"][0]["ctx"].user_id)
    check.equal(recorded["calls"][0]["idp_subject"], "not-a-uuid")


def test_missing_subject_does_not_open_a_session(recorded):
    """セッションのユーザーに sub が無ければ ValueError で、DB のセッションを開かない。"""
    with pytest.raises(ValueError):
        login_sync.sync_app_user_on_login(_session_data(sub=None), tenant_id=TENANT_ID, tenant_code="alpha")
    check.equal(recorded["opened"], [])


def test_deactivated_error_propagates_and_context_is_restored(recorded):
    """無効化されたユーザーの例外は呼び出し側に伝え、テナントコンテキストは戻す。"""
    recorded["error"] = UserDeactivatedError(uuid.uuid4())
    with pytest.raises(UserDeactivatedError):
        login_sync.sync_app_user_on_login(_session_data(), tenant_id=TENANT_ID, tenant_code="alpha")
    check.is_none(get_tenant_context())
