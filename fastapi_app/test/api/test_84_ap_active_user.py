# -*- coding: utf-8 -*-
"""/api/v1 全体の ``require_active_app_user``(無効化ユーザーのセッション失効。01 PF-USR-03、05 #32)と、/api/v1/me の ``user.id`` のテスト。

``require_active_app_user`` は実物(DB の ``t_user`` を引く)。テナントは台帳に作る使い捨て(``ap_tenant``)で、alpha / beta には触れない。
AP のデータは終了時に削除する。Redis は ``FakeRedis``。
"""
import time
import uuid

import pytest
import pytest_check as check

from main_app.route.auth.login_sync import sync_app_user_on_login
from modules.auth import dependency, session
from modules.auth.plane import Plane

from .conftest import cookie_header, make_tokens, with_csrf

ME = "/api/v1/me"
USERS = "/api/v1/users"
ORGS = "/api/v1/organizations"
AP_ENDPOINTS = [("GET", ME), ("GET", USERS), ("GET", ORGS)]

pytestmark = pytest.mark.usefixtures("fake_idp_user_service")


@pytest.fixture
def world(ap_tenant, ap_login):
    """テナント A(管理者・メンバー)とテナント B(メンバー)。"""

    class World:
        a = ap_tenant()
        b = ap_tenant()

    World.admin_a = ap_login(World.a)
    World.member_a = ap_login(World.a, roles=("member",))
    World.member_b = ap_login(World.b, roles=("member",))
    return World


def set_active(ap_db, tenant, user_id, active: bool) -> None:
    """管理画面を介さず DB で is_active を切り替える(次のリクエストで拒否されることの確認用)。"""
    with ap_db.session(tenant.ctx) as db:
        db.connection().exec_driver_sql("UPDATE t_user SET is_active = %s WHERE id = %s", (active, user_id))
        db.commit()


def app_sessions(fake_redis) -> list[str]:
    return [key for key in fake_redis.data if key.startswith("session:app:")]


class TestDeactivatedUser:
    """無効化されたユーザーは次のリクエストで 401 になり、セッションが破棄される。"""

    @pytest.mark.parametrize(("method", "path"), AP_ENDPOINTS)
    def test_deactivated_user_gets_401_and_session_is_deleted(self, client, world, ap_db, fake_redis, method, path):
        """is_active=false のユーザーは、AP のどのエンドポイントでも 401(user_deactivated)。Redis のセッションは削除され、以後は session_expired。"""
        set_active(ap_db, world.a, world.member_a.user_id, False)
        before = len(app_sessions(fake_redis))
        response = client.request(method, path, headers=world.member_a.headers)
        body = response.json()
        check.equal((response.status_code, body["code"]), (401, "user_deactivated"))
        check.equal(len(app_sessions(fake_redis)), before - 1)
        again = client.request(method, path, headers=world.member_a.headers)
        check.equal((again.status_code, again.json()["code"]), (401, "session_expired"))

    def test_effective_immediately_without_caching(self, client, world, ap_db):
        """有効な間は通り、無効化した直後のリクエストから拒否される(キャッシュしない)。"""
        check.equal(client.get(ME, headers=world.member_a.headers).status_code, 200)
        set_active(ap_db, world.a, world.member_a.user_id, False)
        check.equal(client.get(ME, headers=world.member_a.headers).status_code, 401)

    def test_other_users_sessions_are_unaffected(self, client, world, ap_db, fake_redis):
        """あるユーザーの無効化は、同じテナントの他のユーザー・他テナントのユーザーのセッションに影響しない。"""
        set_active(ap_db, world.a, world.member_a.user_id, False)
        client.get(ME, headers=world.member_a.headers)
        check.equal(client.get(ME, headers=world.admin_a.headers).status_code, 200)
        check.equal(client.get(ME, headers=world.member_b.headers).status_code, 200)

    def test_deactivation_through_api_expires_the_session(self, client, world, fake_redis):
        """管理者が API で無効化すると(IdP も無効化)、そのユーザーの次のリクエストが 401(user_deactivated)になる。管理者のセッションは有効なまま。"""
        member_before = client.get(ME, headers=world.member_a.headers)
        check.equal(member_before.status_code, 200)
        patch = client.patch(f"{USERS}/{world.member_a.user_id}", json={"is_active": False}, headers=with_csrf(world.admin_a.headers, **{"If-Match": '"1"'}))
        check.equal(patch.status_code, 200, patch.text)
        after = client.get(ME, headers=world.member_a.headers)
        check.equal((after.status_code, after.json()["code"]), (401, "user_deactivated"))
        check.equal(client.get(ME, headers=world.admin_a.headers).status_code, 200)

    def test_reactivated_user_needs_a_new_session(self, client, world, ap_db, login_ap):
        """有効に戻しても破棄されたセッションは戻らない(再ログインが必要)。新しいセッションなら通る。"""
        set_active(ap_db, world.a, world.member_a.user_id, False)
        client.get(ME, headers=world.member_a.headers)
        set_active(ap_db, world.a, world.member_a.user_id, True)
        check.equal(client.get(ME, headers=world.member_a.headers).status_code, 401)
        fresh = login_ap(world.a.code, world.a.id, ["member"], sub=world.member_a.sub)
        check.equal(client.get(ME, headers=fresh).status_code, 200)

    def test_write_by_deactivated_user_is_rejected_after_csrf(self, client, world, ap_db):
        """無効化された管理者の変更系リクエストは 401 で処理されない(ルーターの依存の順序: テナント → CSRF → 有効確認)。CSRF ヘッダー無しなら先に 403。"""
        set_active(ap_db, world.a, world.admin_a.user_id, False)
        no_csrf = client.post(ORGS, json={"name": "x"}, headers=world.admin_a.headers)
        check.equal(no_csrf.status_code, 403)
        with_header = client.post(ORGS, json={"name": "x"}, headers=with_csrf(world.admin_a.headers))
        check.equal((with_header.status_code, with_header.json()["code"]), (401, "user_deactivated"))
        check.equal(ap_db.orgs(world.a.ctx), [])


class TestNotSynced:
    """AP のユーザー行が無いセッション(ログイン同期前)は 401(user_not_synced)で破棄される。"""

    @pytest.mark.parametrize(("method", "path"), AP_ENDPOINTS)
    def test_session_without_user_row(self, client, world, login_ap, fake_redis, method, path):
        """t_user に行が無い sub のセッションは 401(user_not_synced)。セッションは破棄され、再ログインで同期される。"""
        headers = login_ap(world.a.code, world.a.id, ["tenant_admin"], sub=f"never-synced-{uuid.uuid4()}")
        before = len(app_sessions(fake_redis))
        response = client.request(method, path, headers=headers)
        check.equal((response.status_code, response.json()["code"]), (401, "user_not_synced"))
        check.equal(len(app_sessions(fake_redis)), before - 1)

    def test_same_sub_in_another_tenant_is_not_enough(self, client, world, login_ap):
        """他テナントに同じ sub のユーザー行があっても、このテナントに無ければ user_not_synced(テナントごとに別のユーザー)。"""
        headers = login_ap(world.a.code, world.a.id, ["member"], sub=world.member_b.sub)
        response = client.get(ME, headers=headers)
        check.equal((response.status_code, response.json()["code"]), (401, "user_not_synced"))


class TestScope:
    """有効確認は AP のルーターだけ。CP・公開 API には適用されない。"""

    def test_cp_api_does_not_need_an_ap_user_row(self, client, admin):
        """CP の API は AP のユーザー行を必要としない。"""
        check.equal(client.get("/api/v1/cp/tenants", headers=admin).status_code, 200)

    def test_public_api_is_open(self, client):
        """公開 API(ヘルスチェック)は認証もユーザー確認も不要。"""
        check.equal(client.get("/api/v1/public/health/live").status_code, 200)

    def test_suspended_tenant_is_403_before_user_check(self, client, ap_tenant, ap_login, fake_redis):
        """停止中のテナントは 403(tenant_unavailable 系)で、ユーザーの有効確認より先に拒否され、セッションは破棄されない。"""
        tenant = ap_tenant("SUSPENDED")
        actor = ap_login(tenant)
        before = len(app_sessions(fake_redis))
        response = client.get(ME, headers=actor.headers)
        check.equal(response.status_code, 403)
        check.equal(len(app_sessions(fake_redis)), before)


class TestMe:
    """/api/v1/me の user.id は t_user.id(IdP の sub ではない)。"""

    def test_user_id_is_t_user_id(self, client, world, ap_db):
        """user.id は AP のユーザー ID(t_user.id)で、ユーザー一覧の id・組織のメンバー ID と同じ値。sub とは異なる。"""
        body = client.get(ME, headers=world.admin_a.headers).json()
        check.equal(body["user"]["id"], str(world.admin_a.user_id))
        check.not_equal(body["user"]["id"], world.admin_a.sub)
        check.equal(ap_db.user(world.a.ctx, uuid.UUID(body["user"]["id"]))["idp_subject"], world.admin_a.sub)
        listed = client.get(USERS, headers=world.admin_a.headers).json()["items"]
        check.is_in(body["user"]["id"], [item["id"] for item in listed])

    def test_each_tenant_gets_its_own_user_and_tenant(self, client, world):
        """A のユーザーと B のユーザーは、それぞれ自分のテナント・自分の t_user.id を受け取る。"""
        a = client.get(ME, headers=world.member_a.headers).json()
        b = client.get(ME, headers=world.member_b.headers).json()
        check.equal((a["tenant"], a["user"]["id"]), ({"id": str(world.a.id), "tenant_code": world.a.code}, str(world.member_a.user_id)))
        check.equal((b["tenant"], b["user"]["id"]), ({"id": str(world.b.id), "tenant_code": world.b.code}, str(world.member_b.user_id)))
        check.equal(a["user"]["roles"], ["member"])

    def test_user_id_matches_the_audit_actor(self, client, world, ap_db):
        """/me の user.id で作った操作の監査ログの actor_id が一致する(操作者の解決が t_user.id になっている)。"""
        me = client.get(ME, headers=world.admin_a.headers).json()["user"]["id"]
        client.post(ORGS, json={"name": "監査"}, headers=with_csrf(world.admin_a.headers))
        audit = ap_db.audits(world.a.ctx, "organization.create")
        check.equal([str(a["actor_id"]) for a in audit], [me])


class TestTokenRefreshDoesNotSync:
    """トークン更新ではログイン同期を行わない(last_login_at を更新しない。PF-USR-05)。"""

    def test_refresh_keeps_last_login_at(self, client, world, ap_db, monkeypatch):
        """アクセストークンが切れていて refresh で更新されるリクエストを通しても、t_user.last_login_at・version は変わらない。"""
        sub = f"login-{uuid.uuid4()}"
        result = sync_app_user_on_login(
            {"user": {"sub": sub, "email": "refresh@example.com", "name": "Refresh User"}}, tenant_id=world.a.id, tenant_code=world.a.code
        )
        before = ap_db.user(world.a.ctx, result.user_id)
        check.is_not_none(before["last_login_at"])

        tokens = make_tokens()
        tokens["access_token_expires_at"] = time.time() - 10
        user = {"sub": sub, "preferred_username": "refresh", "email": "refresh@example.com", "realm": f"tenant-{world.a.code}", "plane": "app", "roles": ["member"], "tenant_id": str(world.a.id)}
        data = {"plane": "app", "realm": f"tenant-{world.a.code}", "tenant_id": str(world.a.id), "tenant_code": world.a.code, "tokens": tokens, "user": user}
        headers = cookie_header(rf_sid_app=session.sign_session_id(Plane.APP, session.create_session(Plane.APP, data)))
        refreshed = []

        def fake_refresh(token_url, client_id, client_secret, refresh_token):
            refreshed.append(refresh_token)
            return make_tokens()

        monkeypatch.setattr(dependency, "refresh_access_token", fake_refresh)
        response = client.get(ME, headers=headers)
        check.equal(response.status_code, 200, response.text)
        check.equal(len(refreshed), 1)
        after = ap_db.user(world.a.ctx, result.user_id)
        check.equal((after["last_login_at"], after["version"]), (before["last_login_at"], before["version"]))
