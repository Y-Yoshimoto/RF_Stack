# -*- coding: utf-8 -*-
"""AP のユーザー管理(``UserService``)が使うテナントレルムの Keycloak のフェイク。

``keycloak_admin/fake_server.py`` の ``FakeKeycloakServer``(``httpx.MockTransport``)を拡張し、``tenant_users`` が呼ぶ
ユーザー操作(取得・作成・更新・削除・ログアウト・パスワード設定・レルムロールの付与/解除/available/composite)を実装する。
外部の Keycloak には接続しない。

- ``idp.factory``: ``UserService(kc_admin_factory=...)`` に渡す関数(レルム名を受け取り管理クライアントを返す)。呼び出されたレルム名を記録する
- ``idp.users(realm)``: レルム内のユーザー(表現)
- ``idp.fail(method, path_regex, status)``: 該当リクエストを指定のステータスで失敗させる(基底クラス)
- ``idp.after(method, path_regex, func)``: 該当リクエストが成功した直後に ``func()`` を実行する(並行処理で AP 側が先に変わった状況の再現)
"""
import re
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from keycloak_admin.fake_server import FakeKeycloakServer, RealmState

from modules.keycloak_admin import KeycloakAdminClient

TENANT_ROLES = ("tenant_admin", "member")


class TenantRealmIdp(FakeKeycloakServer):
    """テナントレルムのユーザー管理だけを実装した、状態を持つ Keycloak のフェイク。"""

    def __init__(self) -> None:
        super().__init__()
        self.factory_realms: list[str] = []
        self.logouts: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.password_sets: list[tuple[str, str, str, bool]] = []
        self._after: list[tuple[str, re.Pattern[str], Callable[[], None]]] = []

    # ------------------------------------------------------------------ 公開
    def ensure_realm(self, name: str) -> RealmState:
        """テナントレルムを(無ければ)作る。ロール ``tenant_admin`` / ``member`` を持ち、``member`` は既定ロールに含まれる。"""
        state = self.realms.get(name)
        if state is not None:
            return state
        default_role = f"default-roles-{name}"
        state = RealmState(rep={"realm": name})
        for role in (*TENANT_ROLES, default_role):
            state.roles[role] = {"id": str(uuid.uuid4()), "name": role}
        state.default_composites = ["member"]
        self.realms[name] = state
        return state

    def state_for(self, realm: str) -> RealmState:
        """レルムの状態(無ければ作る)。"""
        return self.ensure_realm(realm)

    def factory(self, realm: str) -> KeycloakAdminClient:
        """``kc_admin_factory`` に渡す関数。レルム名を記録し、そのレルムに接続した管理クライアントを返す。"""
        self.factory_realms.append(realm)
        self.ensure_realm(realm)
        return self.admin()

    def users(self, realm: str) -> dict[str, dict[str, Any]]:
        """レルム内のユーザー(ID → 表現)。"""
        return self.ensure_realm(realm).users

    def user_by_email(self, realm: str, email: str) -> dict[str, Any] | None:
        return next((u for u in self.users(realm).values() if (u.get("email") or "").lower() == email.lower()), None)

    def direct_roles(self, realm: str, user_id: str) -> list[str]:
        return sorted(self.ensure_realm(realm).user_realm_roles.get(user_id, []))

    def passwords(self, realm: str) -> dict[str, dict[str, Any]]:
        return self.ensure_realm(realm).passwords

    def seed_user(self, realm: str, *, username: str, email: str, first_name: str = "Seed", last_name: str = "User", roles: tuple[str, ...] = ("member",), enabled: bool = True) -> str:
        """IdP にユーザーを直接作る(AP の行とは別に、IdP だけに存在するユーザーの準備)。"""
        state = self.ensure_realm(realm)
        user_id = str(uuid.uuid4())
        state.users[user_id] = {"id": user_id, "username": username.lower(), "email": email, "firstName": first_name, "lastName": last_name, "enabled": enabled}
        state.user_realm_roles[user_id] = list(roles)
        return user_id

    def after(self, method: str, path_regex: str, func: Callable[[], None]) -> None:
        """該当リクエストが成功(2xx)した直後に ``func`` を実行する。"""
        self._after.append((method, re.compile(path_regex), func))

    # ------------------------------------------------------------------ ハンドラ
    def _dispatch(self, request: httpx.Request, path: str, body: Any) -> httpx.Response:
        response = super()._dispatch(request, path, body)
        if response.status_code < 300:
            for method, pattern, func in list(self._after):
                if method == request.method and pattern.search(path):
                    func()
        return response

    def _users(self, method: str, state: RealmState, rest: list[str], body: Any, params: dict) -> httpx.Response:
        realm = state.rep["realm"]
        if not rest:
            if method == "GET":
                found = [u for u in state.users.values() if "username" not in params or u["username"] == params["username"].lower()]
                return httpx.Response(200, json=found)
            if method == "POST":
                username = body["username"].lower()
                email = (body.get("email") or "").lower()
                duplicate = any(u["username"] == username or (email and (u.get("email") or "").lower() == email) for u in state.users.values())
                if duplicate:
                    return httpx.Response(409, json={"errorMessage": "User exists with same username or email"})
                user_id = str(uuid.uuid4())
                state.users[user_id] = {"id": user_id, "enabled": True, **body, "username": username}
                return httpx.Response(201, headers={"Location": f"http://keycloak.test/keycloak/admin/realms/{realm}/users/{user_id}"})
            return httpx.Response(405)

        user_id, tail = rest[0], rest[1:]
        user = state.users.get(user_id)
        if user is None:
            return httpx.Response(404, json={"error": "User not found"})
        if not tail:
            if method == "GET":
                return httpx.Response(200, json=user)
            if method == "PUT":
                user.update(body)
                return httpx.Response(204)
            if method == "DELETE":
                state.users.pop(user_id)
                state.passwords.pop(user_id, None)
                state.user_realm_roles.pop(user_id, None)
                self.deleted.append((realm, user_id))
                return httpx.Response(204)
        if tail == ["logout"] and method == "POST":
            self.logouts.append((realm, user_id))
            return httpx.Response(204)
        if tail == ["reset-password"] and method == "PUT":
            state.passwords[user_id] = {"value": body["value"], "temporary": body["temporary"]}
            self.password_sets.append((realm, user_id, body["value"], bool(body["temporary"])))
            if body["temporary"]:
                actions = user.setdefault("requiredActions", [])
                if "UPDATE_PASSWORD" not in actions:
                    actions.append("UPDATE_PASSWORD")
            return httpx.Response(204)
        if tail[:2] == ["role-mappings", "realm"]:
            return self._realm_role_mappings(method, state, user_id, tail[2:], body)
        return httpx.Response(404)

    def _realm_role_mappings(self, method: str, state: RealmState, user_id: str, rest: list[str], body: Any) -> httpx.Response:
        direct = state.user_realm_roles.setdefault(user_id, [])
        default_role = f"default-roles-{state.rep['realm']}"
        if not rest:
            if method == "GET":
                return httpx.Response(200, json=[state.roles[name] for name in direct])
            by_id = {role["id"]: role["name"] for role in state.roles.values()}
            if method == "POST":
                for ref in body:
                    name = by_id[ref["id"]]
                    if name not in direct:
                        direct.append(name)
                return httpx.Response(204)
            if method == "DELETE":
                for ref in body:
                    name = by_id[ref["id"]]
                    if name in direct:
                        direct.remove(name)
                return httpx.Response(204)
        if rest == ["available"] and method == "GET":
            return httpx.Response(200, json=[role for name, role in state.roles.items() if name not in direct and name != default_role])
        if rest == ["composite"] and method == "GET":
            effective = {*direct, *state.default_composites, default_role}
            return httpx.Response(200, json=[state.roles[name] for name in sorted(effective)])
        return httpx.Response(404)
