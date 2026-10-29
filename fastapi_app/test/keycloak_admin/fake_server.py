# -*- coding: utf-8 -*-
"""状態を持つ Keycloak Admin API のフェイク(``httpx.MockTransport`` のハンドラ)。

``modules.keycloak_admin.templates`` のように 1 回の呼び出しで多数のリクエストを送る関数を、
リクエスト単位の応答登録なしで検証するために使う。レルム・ロール・クライアント・マッパー・ユーザー・パスワード・
ロールマッピングをメモリに保持し、実際の Keycloak と同様に 201 / 204 / 404 / 409 を返す。

主な機能:
    - ``server.admin()``: このフェイクに接続した ``KeycloakAdminClient``
    - ``server.writes``: 書き込み系リクエスト(POST / PUT / DELETE)の記録
    - ``server.race_on_create(method, path_regex)``: 最初の該当リクエストで「先に別の処理が作成した」状況を再現する
      (作成は実行して状態に反映し、レスポンスだけ 409 にする)
    - ``server.fail(method, path_regex, status, ...)``: 該当リクエストを指定のステータスで失敗させる
"""
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import httpx

from modules.keycloak_admin import KeycloakAdminClient
from modules.keycloak_admin.token_provider import PasswordGrantTokenProvider

BASE_URL = "http://keycloak.test/keycloak"
ADMIN_PREFIX = "/keycloak/admin/realms"
TOKEN_PATH = "/keycloak/realms/master/protocol/openid-connect/token"
REALM_MANAGEMENT_ROLES = ("manage-users", "view-users", "query-users", "manage-realm", "manage-clients", "view-realm", "impersonation")


@dataclass
class RealmState:
    """レルム 1 つ分の状態。"""

    rep: dict[str, Any]
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_composites: list[str] = field(default_factory=list)
    clients: dict[str, dict[str, Any]] = field(default_factory=dict)
    client_roles: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    mappers: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    passwords: dict[str, dict[str, Any]] = field(default_factory=dict)
    user_realm_roles: dict[str, list[str]] = field(default_factory=dict)
    user_client_roles: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def client_by_client_id(self, client_id: str) -> dict[str, Any] | None:
        return next((c for c in self.clients.values() if c["clientId"] == client_id), None)

    def user_by_name(self, username: str) -> dict[str, Any] | None:
        return next((u for u in self.users.values() if u["username"] == username.lower()), None)


def _stringify_keys(value: Any) -> Any:
    """辞書のキーを文字列にして JSON にできる形へ変換する(タプルのキーがあるため)。"""
    if isinstance(value, dict):
        return {str(key): _stringify_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_keys(item) for item in value]
    return value


@dataclass
class _Rule:
    method: str
    pattern: re.Pattern[str]
    status: int | None
    times: int
    after_create: bool = False
    used: int = 0


class FakeKeycloakServer:
    """メモリ上の Keycloak。``admin()`` で接続済みのクライアントを得る。"""

    def __init__(self) -> None:
        self.realms: dict[str, RealmState] = {}
        self.requests: list[tuple[str, str, Any]] = []
        self.rules: list[_Rule] = []
        self.token_requests = 0
        self.http = httpx.Client(transport=httpx.MockTransport(self._handle))

    # ------------------------------------------------------------------ 公開
    def admin(self, **kwargs: Any) -> KeycloakAdminClient:
        """このフェイクに接続した管理クライアントを作る。"""
        provider = PasswordGrantTokenProvider(f"http://keycloak.test{TOKEN_PATH}", "admin", "fake-admin-password")
        return KeycloakAdminClient(BASE_URL, provider, http_client=self.http, **kwargs)

    @property
    def writes(self) -> list[tuple[str, str, Any]]:
        """書き込み系リクエスト(メソッド、パス、JSON ボディ)。"""
        return [r for r in self.requests if r[0] in ("POST", "PUT", "DELETE")]

    def writes_to(self, method: str, path_regex: str) -> list[tuple[str, str, Any]]:
        """条件に合う書き込み系リクエストを返す。"""
        pattern = re.compile(path_regex)
        return [r for r in self.writes if r[0] == method and pattern.search(r[1])]

    def race_on_create(self, method: str, path_regex: str, times: int = 1) -> None:
        """最初の ``times`` 回の該当リクエストで、作成を実行したうえで 409 を返す(並行実行で先に作成された状況)。"""
        self.rules.append(_Rule(method, re.compile(path_regex), 409, times, after_create=True))

    def fail(self, method: str, path_regex: str, status: int, times: int = 1_000_000) -> None:
        """該当リクエストを、処理せずに指定のステータスで失敗させる。"""
        self.rules.append(_Rule(method, re.compile(path_regex), status, times))

    def snapshot(self) -> str:
        """状態全体の JSON 表現(状態が変わっていないことの比較用)。"""
        return json.dumps({name: _stringify_keys(state.__dict__) for name, state in self.realms.items()}, sort_keys=True, default=str)

    # ------------------------------------------------------------------ ハンドラ
    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.split(b"?", 1)[0].decode()
        if path == TOKEN_PATH:
            self.token_requests += 1
            return httpx.Response(200, json={"access_token": f"fake-token-{self.token_requests}", "expires_in": 300})
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        for rule in self.rules:
            if rule.method == request.method and rule.pattern.search(path) and rule.used < rule.times:
                rule.used += 1
                if rule.after_create:
                    self._dispatch(request, path, body)
                return httpx.Response(rule.status or 500, json={"errorMessage": "injected"})
        return self._dispatch(request, path, body)

    def _dispatch(self, request: httpx.Request, path: str, body: Any) -> httpx.Response:
        method = request.method
        if not path.startswith(ADMIN_PREFIX):
            return httpx.Response(404)
        parts = [unquote(p) for p in path[len(ADMIN_PREFIX):].strip("/").split("/") if p]
        params = dict(request.url.params)
        if not parts:
            return self._create_realm(body) if method == "POST" else httpx.Response(405)
        realm_name, rest = parts[0], parts[1:]
        state = self.realms.get(realm_name)
        if not rest:
            return self._realm(method, realm_name, state, body)
        if state is None:
            return httpx.Response(404, json={"error": "Realm not found."})
        route = {"roles": self._roles, "clients": self._clients, "users": self._users}.get(rest[0])
        if route is None:
            return httpx.Response(404)
        return route(method, state, rest[1:], body, params)

    # ------------------------------------------------------------------ レルム
    def _create_realm(self, body: dict) -> httpx.Response:
        name = body["realm"]
        if name in self.realms:
            return httpx.Response(409, json={"errorMessage": "Conflict detected."})
        state = RealmState(rep={**body, "defaultRole": {"name": f"default-roles-{name.lower()}"}})
        default_role = f"default-roles-{name.lower()}"
        state.roles[default_role] = {"id": str(uuid.uuid4()), "name": default_role}
        management_id = str(uuid.uuid4())
        state.clients[management_id] = {"id": management_id, "clientId": "realm-management"}
        state.client_roles[management_id] = {role: {"id": str(uuid.uuid4()), "name": role} for role in REALM_MANAGEMENT_ROLES}
        self.realms[name] = state
        return httpx.Response(201, headers={"Location": f"{BASE_URL}/admin/realms/{name}"})

    def _realm(self, method: str, name: str, state: RealmState | None, body: Any) -> httpx.Response:
        if state is None:
            return httpx.Response(404, json={"error": "Realm not found."})
        if method == "GET":
            return httpx.Response(200, json=state.rep)
        if method == "PUT":
            state.rep.update(body)
            return httpx.Response(204)
        if method == "DELETE":
            del self.realms[name]
            return httpx.Response(204)
        return httpx.Response(405)

    # ------------------------------------------------------------------ ロール
    def _roles(self, method: str, state: RealmState, rest: list[str], body: Any, params: dict) -> httpx.Response:
        if not rest:
            if method != "POST":
                return httpx.Response(405)
            if body["name"] in state.roles:
                return httpx.Response(409, json={"errorMessage": "Role with name exists."})
            state.roles[body["name"]] = {"id": str(uuid.uuid4()), **body}
            return httpx.Response(201)
        name = rest[0]
        if len(rest) == 1 and method == "GET":
            role = state.roles.get(name)
            return httpx.Response(200, json=role) if role else httpx.Response(404)
        if rest[1:2] == ["composites"] and name == f"default-roles-{state.rep['realm'].lower()}":
            if method == "POST" and len(rest) == 2:
                by_id = {r["id"]: r["name"] for r in state.roles.values()}
                for ref in body:
                    if by_id.get(ref["id"]) not in state.default_composites:
                        state.default_composites.append(by_id[ref["id"]])
                return httpx.Response(204)
            if method == "GET" and rest[2:] == ["realm"]:
                return httpx.Response(200, json=[state.roles[r] for r in state.default_composites])
        return httpx.Response(404)

    # ------------------------------------------------------------------ クライアント
    def _clients(self, method: str, state: RealmState, rest: list[str], body: Any, params: dict) -> httpx.Response:
        if not rest:
            if method == "GET":
                found = [c for c in state.clients.values() if "clientId" not in params or c["clientId"] == params["clientId"]]
                return httpx.Response(200, json=found)
            if method == "POST":
                if state.client_by_client_id(body["clientId"]):
                    return httpx.Response(409, json={"errorMessage": "Client already exists"})
                client_id = str(uuid.uuid4())
                state.clients[client_id] = {"id": client_id, **body}
                if body.get("serviceAccountsEnabled"):
                    user_id = str(uuid.uuid4())
                    state.users[user_id] = {"id": user_id, "username": f"service-account-{body['clientId']}".lower(), "serviceAccountClientId": client_id}
                return httpx.Response(201, headers={"Location": f"{BASE_URL}/admin/realms/{state.rep['realm']}/clients/{client_id}"})
            return httpx.Response(405)
        client_id, tail = rest[0], rest[1:]
        client = state.clients.get(client_id)
        if client is None:
            return httpx.Response(404)
        if not tail and method == "PUT":
            client.update(body)
            return httpx.Response(204)
        if tail == ["service-account-user"] and method == "GET":
            user = next((u for u in state.users.values() if u.get("serviceAccountClientId") == client_id), None)
            return httpx.Response(200, json=user) if user else httpx.Response(404)
        if tail[:1] == ["roles"] and len(tail) == 2 and method == "GET":
            role = state.client_roles.get(client_id, {}).get(tail[1])
            return httpx.Response(200, json=role) if role else httpx.Response(404)
        if tail[:2] == ["protocol-mappers", "models"]:
            mappers = state.mappers.setdefault(client_id, {})
            if len(tail) == 2 and method == "GET":
                return httpx.Response(200, json=list(mappers.values()))
            if len(tail) == 2 and method == "POST":
                if any(m["name"] == body["name"] for m in mappers.values()):
                    return httpx.Response(409, json={"errorMessage": "Protocol mapper exists with same name"})
                mapper_id = str(uuid.uuid4())
                mappers[mapper_id] = {"id": mapper_id, **body}
                return httpx.Response(201, headers={"Location": f"{BASE_URL}/x/protocol-mappers/models/{mapper_id}"})
            if len(tail) == 3 and method == "PUT" and tail[2] in mappers:
                mappers[tail[2]].update(body)
                return httpx.Response(204)
        return httpx.Response(404)

    # ------------------------------------------------------------------ ユーザー
    def _users(self, method: str, state: RealmState, rest: list[str], body: Any, params: dict) -> httpx.Response:
        if not rest:
            if method == "GET":
                found = [u for u in state.users.values() if "username" not in params or u["username"] == params["username"].lower()]
                return httpx.Response(200, json=found)
            if method == "POST":
                duplicate_email = body.get("email") and any(u.get("email") == body["email"] for u in state.users.values())
                if state.user_by_name(body["username"]) or duplicate_email:
                    return httpx.Response(409, json={"errorMessage": "User exists with same username or email"})
                user_id = str(uuid.uuid4())
                state.users[user_id] = {"id": user_id, **body, "username": body["username"].lower()}
                return httpx.Response(201, headers={"Location": f"{BASE_URL}/admin/realms/{state.rep['realm']}/users/{user_id}"})
            return httpx.Response(405)
        user_id, tail = rest[0], rest[1:]
        user = state.users.get(user_id)
        if user is None:
            return httpx.Response(404)
        if not tail and method == "PUT":
            user.update(body)
            return httpx.Response(204)
        if tail == ["reset-password"] and method == "PUT":
            state.passwords[user_id] = {"value": body["value"], "temporary": body["temporary"]}
            if body["temporary"]:
                actions = user.setdefault("requiredActions", [])
                if "UPDATE_PASSWORD" not in actions:
                    actions.append("UPDATE_PASSWORD")
            return httpx.Response(204)
        if tail == ["role-mappings", "realm"]:
            if method == "GET":
                return httpx.Response(200, json=[state.roles[n] for n in state.user_realm_roles.get(user_id, [])])
            if method == "POST":
                by_id = {r["id"]: r["name"] for r in state.roles.values()}
                for ref in body:
                    state.user_realm_roles.setdefault(user_id, []).append(by_id[ref["id"]])
                return httpx.Response(204)
        if tail[:2] == ["role-mappings", "clients"] and len(tail) == 3:
            key = (user_id, tail[2])
            roles = state.client_roles.get(tail[2], {})
            if method == "GET":
                return httpx.Response(200, json=[roles[n] for n in state.user_client_roles.get(key, [])])
            if method == "POST":
                by_id = {r["id"]: r["name"] for r in roles.values()}
                for ref in body:
                    state.user_client_roles.setdefault(key, []).append(by_id[ref["id"]])
                return httpx.Response(204)
        return httpx.Response(404)

