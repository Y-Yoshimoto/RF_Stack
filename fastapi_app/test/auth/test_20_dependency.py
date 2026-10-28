# -*- coding: utf-8 -*-
"""modules.auth.dependency(プレーン別の認証依存関数・require_*_roles・トークン更新)のテスト。"""
import json

import pytest
import pytest_check as check
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from modules.auth import dependency, session
from modules.auth.dependency import get_current_app_user, get_current_cp_user, load_session, require_app_roles, require_cp_roles
from modules.auth.plane import Plane
from modules.keycloak_admin.client_secret import derive_client_secret

from .conftest import SEED, make_session_data, make_tokens


def _cookie(**cookies: str) -> dict[str, str]:
    """リクエストヘッダーとして Cookie を渡す(TestClient の per-request cookies は非推奨のため)。"""
    return {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/app/me")
    def app_me(user: dict = Depends(get_current_app_user)):
        return {"sub": user["sub"], "plane": user["plane"]}

    @app.get("/cp/me")
    def cp_me(user: dict = Depends(get_current_cp_user)):
        return {"sub": user["sub"], "plane": user["plane"]}

    @app.get("/app/admin")
    def app_admin(user: dict = Depends(require_app_roles("tenant_admin"))):
        return {"roles": user["roles"]}

    @app.get("/app/any")
    def app_any(user: dict = Depends(require_app_roles("tenant_admin", "member"))):
        return {"roles": user["roles"]}

    @app.get("/cp/admin")
    def cp_admin(user: dict = Depends(require_cp_roles("saas_admin"))):
        return {"roles": user["roles"]}

    @app.get("/cp/any")
    def cp_any(user: dict = Depends(require_cp_roles("saas_admin", "saas_viewer"))):
        return {"roles": user["roles"]}

    return app


@pytest.fixture
def client(config) -> TestClient:
    """認証依存関数を使うルートを持つアプリのクライアント(設定はテスト用)。"""
    return TestClient(_build_app())


class TestCookiePerPlane:
    """プレーンごとの Cookie・署名 salt により、他プレーンのセッションが拒否される。"""

    def test_no_cookie_is_401(self, client):
        """Cookie が無ければどちらのプレーンも 401(Not authenticated)。"""
        for path in ("/app/me", "/cp/me"):
            response = client.get(path)
            check.equal((response.status_code, response.json()), (401, {"detail": "Not authenticated"}))

    def test_own_cookie_is_accepted(self, client, login_as):
        """AP の Cookie は AP のルート、CP の Cookie は CP のルートで認証される。"""
        app_cookie, _ = login_as(Plane.APP, ["member"])
        cp_cookie, _ = login_as(Plane.CP, ["saas_admin"])
        check.equal(client.get("/app/me", headers=_cookie(rf_sid_app=app_cookie)).json(), {"sub": "user-sub-1", "plane": "app"})
        check.equal(client.get("/cp/me", headers=_cookie(rf_sid_cp=cp_cookie)).json(), {"sub": "user-sub-1", "plane": "cp"})

    def test_both_cookies_at_once_do_not_mix(self, client, login_as):
        """同一ブラウザで AP と CP に同時ログインしていても、各ルートは自プレーンの Cookie だけを見る。"""
        app_cookie, _ = login_as(Plane.APP, ["member"])
        cp_cookie, _ = login_as(Plane.CP, ["saas_viewer"])
        cookies = {"rf_sid_app": app_cookie, "rf_sid_cp": cp_cookie}
        check.equal(client.get("/app/me", headers=_cookie(**cookies)).json()["plane"], "app")
        check.equal(client.get("/cp/me", headers=_cookie(**cookies)).json()["plane"], "cp")

    @pytest.mark.parametrize(
        ("issued_for", "path", "cookie_name"),
        [(Plane.APP, "/cp/me", "rf_sid_cp"), (Plane.CP, "/app/me", "rf_sid_app")],
    )
    def test_cookie_value_of_other_plane_is_rejected_as_invalid_session(self, client, login_as, issued_for, path, cookie_name):
        """AP の Cookie 値を CP の Cookie として(または逆に)提示しても、署名の salt が違うので 401(Invalid session)。"""
        value, _ = login_as(issued_for, ["member"] if issued_for == Plane.APP else ["saas_admin"])
        response = client.get(path, headers=_cookie(**{cookie_name: value}))
        check.equal((response.status_code, response.json()), (401, {"detail": "Invalid session"}))

    def test_other_plane_session_id_signed_for_this_plane_finds_no_session(self, client, login_as):
        """AP のセッション ID を CP の salt で署名し直しても、Redis の CP 側のキー空間には無いので 401(Session expired)。"""
        _, app_session_id = login_as(Plane.APP, ["member"])
        forged = session.sign_session_id(Plane.CP, app_session_id)
        response = client.get("/cp/me", headers=_cookie(rf_sid_cp=forged))
        check.equal((response.status_code, response.json()), (401, {"detail": "Session expired"}))

    def test_session_stored_in_wrong_key_space_is_rejected(self, client, fake_redis):
        """CP のデータが AP のキー空間に置かれていても(plane が違う)、401(Invalid session payload)で使えない。"""
        data = make_session_data(Plane.CP, roles=["saas_admin"])
        fake_redis.setex("session:app:planted", 600, json.dumps(data))
        response = client.get("/app/me", headers=_cookie(rf_sid_app=session.sign_session_id(Plane.APP, "planted")))
        check.equal((response.status_code, response.json()), (401, {"detail": "Invalid session payload"}))

    def test_user_plane_must_match(self, client, fake_redis):
        """セッションの plane が合っていても、user.plane が違えば 401(Invalid session payload)。"""
        data = make_session_data(Plane.APP, roles=["member"])
        data["user"]["plane"] = "cp"
        fake_redis.setex("session:app:mixed", 600, json.dumps(data))
        response = client.get("/app/me", headers=_cookie(rf_sid_app=session.sign_session_id(Plane.APP, "mixed")))
        check.equal((response.status_code, response.json()), (401, {"detail": "Invalid session payload"}))

    def test_session_without_user_is_rejected(self, client, fake_redis):
        """user の無いセッションは 401(Invalid session payload)。"""
        data = make_session_data(Plane.APP, roles=["member"])
        del data["user"]
        fake_redis.setex("session:app:nouser", 600, json.dumps(data))
        response = client.get("/app/me", headers=_cookie(rf_sid_app=session.sign_session_id(Plane.APP, "nouser")))
        check.equal(response.status_code, 401)

    def test_deleted_session_is_401(self, client, login_as):
        """削除(ログアウト)したセッションの Cookie は 401(Session expired)。"""
        cookie, sid = login_as(Plane.APP, ["member"])
        session.delete_session(Plane.APP, sid)
        response = client.get("/app/me", headers=_cookie(rf_sid_app=cookie))
        check.equal((response.status_code, response.json()), (401, {"detail": "Session expired"}))


class TestRoleRequirements:
    """require_app_roles / require_cp_roles。"""

    def test_app_admin_route(self, client, login_as):
        """tenant_admin を要求するルートは、member では 403、tenant_admin では 200。"""
        member, _ = login_as(Plane.APP, ["member"])
        admin, _ = login_as(Plane.APP, ["tenant_admin"])
        response = client.get("/app/admin", headers=_cookie(rf_sid_app=member))
        check.equal((response.status_code, response.json()), (403, {"detail": "Forbidden"}))
        check.equal(client.get("/app/admin", headers=_cookie(rf_sid_app=admin)).status_code, 200)

    def test_any_of_the_roles_is_enough(self, client, login_as):
        """複数ロールを指定した場合は、いずれかを持てば通る。"""
        member, _ = login_as(Plane.APP, ["member"])
        viewer, _ = login_as(Plane.CP, ["saas_viewer"])
        check.equal(client.get("/app/any", headers=_cookie(rf_sid_app=member)).status_code, 200)
        check.equal(client.get("/cp/any", headers=_cookie(rf_sid_cp=viewer)).status_code, 200)

    def test_cp_viewer_cannot_use_admin_route(self, client, login_as):
        """saas_viewer は saas_admin 専用のルートで 403。"""
        viewer, _ = login_as(Plane.CP, ["saas_viewer"])
        check.equal(client.get("/cp/admin", headers=_cookie(rf_sid_cp=viewer)).status_code, 403)

    @pytest.mark.parametrize("roles", [[], None])
    def test_user_without_roles_is_forbidden(self, client, login_as, roles):
        """ロールを持たない(空・未設定)ユーザーは 403。"""
        cookie, sid = login_as(Plane.APP, [])
        data = session.get_session(Plane.APP, sid)
        data["user"]["roles"] = roles
        session.update_session(Plane.APP, sid, data)
        check.equal(client.get("/app/any", headers=_cookie(rf_sid_app=cookie)).status_code, 403)

    def test_unauthenticated_is_401_not_403(self, client):
        """未認証はロール不足(403)ではなく認証エラー(401)。"""
        check.equal(client.get("/app/admin").status_code, 401)
        check.equal(client.get("/cp/admin").status_code, 401)

    def test_role_names_of_the_other_plane_cannot_unlock_a_route(self, client, login_as):
        """AP のセッションが(改ざんで)saas_admin を持っていても、CP のルートには CP の Cookie が必要で通らない。"""
        cookie, sid = login_as(Plane.APP, ["member"])
        data = session.get_session(Plane.APP, sid)
        data["user"]["roles"] = ["member", "saas_admin"]
        session.update_session(Plane.APP, sid, data)
        check.equal(client.get("/cp/admin", headers=_cookie(rf_sid_cp=cookie)).status_code, 401)
        check.equal(client.get("/cp/admin", headers=_cookie(rf_sid_app=cookie)).status_code, 401)

    @pytest.mark.parametrize(
        ("factory", "roles"),
        [
            (require_app_roles, ()),
            (require_cp_roles, ()),
            (require_app_roles, ("saas_admin",)),
            (require_cp_roles, ("tenant_admin",)),
            (require_app_roles, ("member", "saas_viewer")),
            (require_app_roles, ("no_such_role",)),
            (require_cp_roles, ("member",)),
        ],
    )
    def test_invalid_role_definitions_fail_at_definition_time(self, factory, roles):
        """ロールが空、またはそのプレーンで扱わないロールを含む定義は、ルート定義時点で ValueError にする。"""
        with pytest.raises(ValueError):
            factory(*roles)


class TestTokenLifecycle:
    """アクセストークンの期限切れ時の更新とセッションの破棄。"""

    def test_expired_refresh_token_destroys_session(self, client, login_as, fake_redis):
        """refresh token も期限切れなら 401 とし、セッションを Redis から削除する。"""
        cookie, sid = login_as(Plane.APP, ["member"], tokens=make_tokens(access_ttl=-10, refresh_ttl=-10))
        response = client.get("/app/me", headers=_cookie(rf_sid_app=cookie))
        check.equal((response.status_code, response.json()), (401, {"detail": "Session expired"}))
        check.is_none(session.get_session(Plane.APP, sid))

    def test_failed_refresh_destroys_session(self, client, login_as, monkeypatch):
        """トークン更新に失敗したら 401 とし、セッションを削除する。"""
        monkeypatch.setattr(dependency, "refresh_access_token", lambda *args, **kwargs: None)
        cookie, sid = login_as(Plane.APP, ["member"], tokens=make_tokens(access_ttl=-10))
        check.equal(client.get("/app/me", headers=_cookie(rf_sid_app=cookie)).status_code, 401)
        check.is_none(session.get_session(Plane.APP, sid))

    @pytest.mark.parametrize(("plane", "roles", "path", "cookie_name", "client_id", "realm"), [
        (Plane.APP, ["member"], "/app/me", "rf_sid_app", "fastapi-app", "tenant-alpha"),
        (Plane.CP, ["saas_admin"], "/cp/me", "rf_sid_cp", "fastapi-cp", "control-plane"),
    ])
    def test_refresh_uses_plane_client_and_keeps_ttl_and_roles(self, client, login_as, fake_redis, monkeypatch, plane, roles, path, cookie_name, client_id, realm):
        """更新は、プレーンのクライアント ID と導出したシークレットで行い、セッションの残り TTL とロールは変えない。"""
        calls = []

        def fake_refresh(token_url, client_id, client_secret, refresh_token):
            calls.append({"token_url": token_url, "client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token})
            return make_tokens() | {"access_token": "new-access", "refresh_token": "new-refresh"}

        monkeypatch.setattr(dependency, "refresh_access_token", fake_refresh)
        cookie, sid = login_as(plane, roles, tokens=make_tokens(access_ttl=-10))
        fake_redis.ttls[f"session:{plane.value}:{sid}"] = 77
        response = client.get(path, headers=_cookie(**{cookie_name: cookie}))
        check.equal(response.status_code, 200)
        check.equal(len(calls), 1)
        check.equal(calls[0]["client_id"], client_id)
        check.equal(calls[0]["client_secret"], derive_client_secret(SEED, realm, client_id))
        check.equal(calls[0]["refresh_token"], "refresh-token-value")
        check.is_in(f"/realms/{realm}/protocol/openid-connect/token", calls[0]["token_url"])
        stored = session.get_session(plane, sid)
        check.equal(stored["tokens"]["access_token"], "new-access")
        check.equal(stored["user"]["roles"], roles)
        check.equal(fake_redis.ttls[f"session:{plane.value}:{sid}"], 77, "更新で TTL を延ばさない")

    def test_valid_token_does_not_call_keycloak(self, client, login_as, monkeypatch):
        """アクセストークンが有効なら Keycloak へは問い合わせない。"""
        monkeypatch.setattr(dependency, "refresh_access_token", lambda *a, **k: pytest.fail("更新してはならない"))
        cookie, _ = login_as(Plane.APP, ["member"], tokens=make_tokens(access_ttl=3600))
        check.equal(client.get("/app/me", headers=_cookie(rf_sid_app=cookie)).status_code, 200)

    def test_load_session_requires_cookie(self):
        """load_session: Cookie 無しは 401(関数として直接呼んだ場合)。"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            load_session(Plane.APP, None)
        check.equal(exc_info.value.status_code, 401)

    def test_token_expiry_leeway_triggers_refresh(self, client, login_as, monkeypatch):
        """期限まで猶予(30 秒)以内のアクセストークンも更新対象になる。"""
        calls = []
        monkeypatch.setattr(dependency, "refresh_access_token", lambda *a, **k: calls.append(1) or make_tokens())
        cookie, _ = login_as(Plane.APP, ["member"], tokens=make_tokens(access_ttl=5))
        client.get("/app/me", headers=_cookie(rf_sid_app=cookie))
        check.equal(len(calls), 1)
