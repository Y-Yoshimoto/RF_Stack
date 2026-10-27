# -*- coding: utf-8 -*-
"""realms / roles / users の ensure 系関数のテスト(「無い→作成」「ある」「作成時 409」の各分岐)。"""
import json as jsonlib

import httpx
import pytest
import pytest_check as check

from modules.keycloak_admin import KeycloakAdminError, RealmSpec, UserSpec, ensure_realm, ensure_realm_role, ensure_user, find_user, get_realm, get_realm_role, set_user_password, validate_realm_name

A = "/keycloak/admin/realms"
R1 = f"{A}/r1"


class TestValidateRealmName:
    """レルム名の検証。"""

    @pytest.mark.parametrize("name", ["a", "tenant-acme", "Tenant_01", "x" * 64])
    def test_valid(self, name):
        """英数字・ハイフン・アンダースコアの 1〜64 文字は有効で、そのまま返る。"""
        check.equal(validate_realm_name(name), name)

    @pytest.mark.parametrize(
        "name",
        [
            "", "x" * 65, "a b", "a/b", "..", "a.b", "日本", None,
            "a\n",
        ],
    )
    def test_invalid(self, name):
        """許可されない文字・長さ・None は ValueError。"""
        with pytest.raises(ValueError):
            validate_realm_name(name)


class TestGetRealm:
    """get_realm。"""

    def test_found_and_not_found(self, kc):
        """200 は辞書、404 は None。"""
        kc.on("GET", R1, httpx.Response(200, json={"realm": "r1"}), httpx.Response(404))
        check.equal(get_realm(kc.admin, "r1"), {"realm": "r1"})
        check.is_none(get_realm(kc.admin, "r1"))

    def test_other_errors_raise(self, kc):
        """404 以外のエラーは例外。"""
        kc.on("GET", R1, status=403)
        with pytest.raises(KeycloakAdminError):
            get_realm(kc.admin, "r1")


class TestEnsureRealm:
    """ensure_realm の分岐。"""

    def test_create_when_missing(self, kc):
        """無ければ POST で作成し created=True。ボディは realm / enabled。"""
        kc.on("GET", R1, status=404)
        kc.on("POST", A, status=201)
        result = ensure_realm(kc.admin, "r1")
        check.equal((result.realm, result.created, result.updated), ("r1", True, False))
        check.equal(kc.requests_to("POST", A)[0].json, {"realm": "r1", "enabled": True})
        check.equal(len(kc.writes), 1)

    def test_create_with_settings_does_not_put(self, kc):
        """設定付きで新規作成した場合は POST に含めるだけで PUT はしない。"""
        kc.on("GET", R1, status=404)
        kc.on("POST", A, status=201)
        result = ensure_realm(kc.admin, RealmSpec(realm="r1", settings={"bruteForceProtected": True}))
        check.is_true(result.created)
        check.equal(kc.requests_to("POST", A)[0].json, {"bruteForceProtected": True, "realm": "r1", "enabled": True})
        check.equal(kc.requests_to("PUT"), [])

    def test_existing_without_settings_makes_no_writes(self, kc):
        """既にあり settings 未指定なら何も書かない(created=False, updated=False)。"""
        kc.on("GET", R1, json={"realm": "r1"})
        result = ensure_realm(kc.admin, "r1")
        check.equal((result.created, result.updated), (False, False))
        check.equal(kc.writes, [])

    def test_existing_with_settings_is_put(self, kc):
        """既にあり settings 指定なら PUT で反映し updated=True。"""
        kc.on("GET", R1, json={"realm": "r1"})
        kc.on("PUT", R1, status=204)
        result = ensure_realm(kc.admin, RealmSpec(realm="r1", settings={"duplicateEmailsAllowed": False, "realm": "ignored"}))
        check.equal((result.created, result.updated), (False, True))
        check.equal(kc.requests_to("PUT", R1)[0].json, {"duplicateEmailsAllowed": False, "realm": "r1", "enabled": True})
        check.equal(kc.requests_to("POST"), [])

    def test_conflict_on_create_without_settings_is_treated_as_existing(self, kc):
        """作成時に 409(並行実行)なら既存扱い。settings が無ければ PUT しない。"""
        kc.on("GET", R1, status=404)
        kc.on("POST", A, status=409, json={"errorMessage": "Conflict detected"})
        result = ensure_realm(kc.admin, "r1")
        check.equal((result.created, result.updated), (False, False))
        check.equal(kc.requests_to("PUT"), [])

    def test_conflict_on_create_with_settings_puts(self, kc):
        """作成時に 409 で settings があれば、既存として PUT で反映する。"""
        kc.on("GET", R1, status=404)
        kc.on("POST", A, status=409)
        kc.on("PUT", R1, status=204)
        result = ensure_realm(kc.admin, RealmSpec(realm="r1", settings={"x": 1}))
        check.equal((result.created, result.updated), (False, True))

    def test_create_failure_raises(self, kc):
        """作成が 201/409 以外で失敗したら例外。"""
        kc.on("GET", R1, status=404)
        kc.on("POST", A, status=403, json={"error": "forbidden"})
        with pytest.raises(KeycloakAdminError, match="create realm r1"):
            ensure_realm(kc.admin, "r1")

    @pytest.mark.parametrize("name", ["", "a b", "../x", "x" * 65])
    def test_invalid_name_sends_nothing(self, kc, name):
        """不正なレルム名は ValueError で、リクエストを 1 つも送らない。"""
        with pytest.raises(ValueError):
            ensure_realm(kc.admin, name)
        check.equal(kc.requests, [])

    def test_is_idempotent(self, kc):
        """作成後に同じ呼び出しをしても書き込みは増えない。"""
        kc.on("GET", R1, httpx.Response(404), httpx.Response(200, json={"realm": "r1"}))
        kc.on("POST", A, status=201)
        first = ensure_realm(kc.admin, "r1")
        second = ensure_realm(kc.admin, "r1")
        check.equal((first.created, second.created), (True, False))
        check.equal(len(kc.writes), 1)


class TestEnsureRealmRole:
    """ensure_realm_role の分岐。"""

    ROLES = f"{R1}/roles"

    def test_existing(self, kc):
        """既にあれば作成せず、既存の id を返す。"""
        kc.on("GET", f"{self.ROLES}/member", json={"id": "role-1", "name": "member"})
        result = ensure_realm_role(kc.admin, "r1", "member")
        check.equal((result.id, result.name, result.created), ("role-1", "member", False))
        check.equal(kc.writes, [])

    @pytest.mark.parametrize(("description", "expected"), [(None, {"name": "member"}), ("説明", {"name": "member", "description": "説明"})])
    def test_create_then_resolve_id(self, kc, description, expected):
        """無ければ POST(description は指定時のみ)し、Location がないため GET し直して id を得る。"""
        kc.on("GET", f"{self.ROLES}/member", httpx.Response(404), httpx.Response(200, json={"id": "role-2", "name": "member"}))
        kc.on("POST", self.ROLES, status=201)
        result = ensure_realm_role(kc.admin, "r1", "member", description=description)
        check.equal((result.id, result.created), ("role-2", True))
        check.equal(kc.requests_to("POST", self.ROLES)[0].json, expected)

    def test_conflict_on_create_is_existing(self, kc):
        """作成時 409 なら既存扱い(created=False)で、取得し直した id を返す。"""
        kc.on("GET", f"{self.ROLES}/member", httpx.Response(404), httpx.Response(200, json={"id": "role-3"}))
        kc.on("POST", self.ROLES, status=409)
        result = ensure_realm_role(kc.admin, "r1", "member")
        check.equal((result.id, result.created), ("role-3", False))

    def test_not_found_after_create_raises(self, kc):
        """作成後に見つからなければ KeycloakAdminError。"""
        kc.on("GET", f"{self.ROLES}/member", status=404)
        kc.on("POST", self.ROLES, status=201)
        with pytest.raises(KeycloakAdminError, match="resolve realm role member"):
            ensure_realm_role(kc.admin, "r1", "member")

    def test_create_failure_raises(self, kc):
        """作成が 201/409 以外なら例外。"""
        kc.on("GET", f"{self.ROLES}/member", status=404)
        kc.on("POST", self.ROLES, status=400, json={"errorMessage": "bad"})
        with pytest.raises(KeycloakAdminError, match="create realm role"):
            ensure_realm_role(kc.admin, "r1", "member")

    def test_role_name_is_encoded_in_url(self, kc):
        """ロール名はパスにエンコードして渡す。"""
        kc.on("GET", f"{self.ROLES}/a%2Fb%20c", json={"id": "x"})
        check.equal(get_realm_role(kc.admin, "r1", "a/b c"), {"id": "x"})


class TestFindUser:
    """find_user。"""

    USERS = f"{R1}/users"

    def test_query_parameters(self, kc):
        """username と exact=true で検索する。"""
        kc.on("GET", self.USERS, json=[])
        find_user(kc.admin, "r1", "alice")
        check.equal(kc.api_requests[0].query, {"username": "alice", "exact": "true"})

    def test_case_insensitive_match(self, kc):
        """Keycloak は小文字に正規化するため、大文字小文字を無視して照合する。"""
        kc.on("GET", self.USERS, json=[{"id": "u1", "username": "alice"}])
        check.equal(find_user(kc.admin, "r1", "ALICE"), {"id": "u1", "username": "alice"})

    def test_picks_exact_among_results(self, kc):
        """複数件返っても、ユーザー名が一致するものだけを選ぶ。"""
        kc.on("GET", self.USERS, json=[{"id": "u2", "username": "alice2"}, {"id": "u1", "username": "alice"}, {"id": "u3"}])
        check.equal(find_user(kc.admin, "r1", "alice")["id"], "u1")

    @pytest.mark.parametrize("body", [[], [{"id": "u2", "username": "bob"}], None, [{"id": "u3", "username": None}]])
    def test_not_found(self, kc, body):
        """空・不一致・null・ユーザー名なしは None。"""
        kc.on("GET", self.USERS, httpx.Response(200, content=jsonlib.dumps(body), headers={"content-type": "application/json"}))
        check.is_none(find_user(kc.admin, "r1", "alice"))


class TestEnsureUser:
    """ensure_user の分岐。"""

    USERS = f"{R1}/users"

    def test_existing_is_not_modified(self, kc):
        """既にいれば作成も更新もしない(created=False)。"""
        kc.on("GET", self.USERS, json=[{"id": "u1", "username": "alice"}])
        result = ensure_user(kc.admin, "r1", UserSpec(username="alice", email="a@example.com"))
        check.equal((result.id, result.username, result.created), ("u1", "alice", False))
        check.equal(kc.writes, [])

    def test_create_with_location(self, kc):
        """無ければ POST し、Location から id を得る(追加の検索はしない)。"""
        kc.on("GET", self.USERS, json=[])
        kc.on("POST", self.USERS, httpx.Response(201, headers={"Location": f"http://kc{self.USERS}/new-id"}))
        result = ensure_user(kc.admin, "r1", UserSpec(username="alice", email="a@example.com", first_name="A", last_name="L"))
        check.equal((result.id, result.created), ("new-id", True))
        check.equal(kc.requests_to("POST")[0].json, {"username": "alice", "enabled": True, "emailVerified": False, "email": "a@example.com", "firstName": "A", "lastName": "L"})
        check.equal(len(kc.requests_to("GET")), 1)

    def test_create_without_location_searches_again(self, kc):
        """Location が無ければ検索し直して id を得る。"""
        kc.on("GET", self.USERS, httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": "found-id", "username": "alice"}]))
        kc.on("POST", self.USERS, status=201)
        result = ensure_user(kc.admin, "r1", "alice")
        check.equal((result.id, result.created), ("found-id", True))
        check.equal(len(kc.requests_to("GET")), 2)

    def test_create_without_location_and_not_found_raises(self, kc):
        """Location が無く、検索しても見つからなければ KeycloakAdminError。"""
        kc.on("GET", self.USERS, json=[])
        kc.on("POST", self.USERS, status=201)
        with pytest.raises(KeycloakAdminError, match="resolve user id for alice"):
            ensure_user(kc.admin, "r1", "alice")

    def test_conflict_and_found_is_existing(self, kc):
        """作成時 409 で、ユーザー名で見つかれば既存扱い(created=False)。"""
        kc.on("GET", self.USERS, httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": "u9", "username": "alice"}]))
        kc.on("POST", self.USERS, status=409, json={"errorMessage": "User exists with same username"})
        result = ensure_user(kc.admin, "r1", "alice")
        check.equal((result.id, result.created), ("u9", False))

    def test_conflict_and_not_found_raises_with_409(self, kc):
        """作成時 409 でユーザー名でも見つからない(メール重複など)なら 409 の KeycloakAdminError。"""
        kc.on("GET", self.USERS, json=[])
        kc.on("POST", self.USERS, status=409)
        with pytest.raises(KeycloakAdminError) as exc_info:
            ensure_user(kc.admin, "r1", "alice")
        check.equal(exc_info.value.status_code, 409)
        check.is_in("duplicate email", exc_info.value.detail)

    def test_create_failure_raises(self, kc):
        """作成が 201/409 以外なら例外。"""
        kc.on("GET", self.USERS, json=[])
        kc.on("POST", self.USERS, status=400, json={"errorMessage": "Please specify username", "field": "username"})
        with pytest.raises(KeycloakAdminError, match="400"):
            ensure_user(kc.admin, "r1", "alice")

    def test_string_spec_is_username(self, kc):
        """文字列を渡すとユーザー名として扱う。"""
        kc.on("GET", self.USERS, json=[])
        kc.on("POST", self.USERS, httpx.Response(201, headers={"Location": "http://kc/users/id1"}))
        ensure_user(kc.admin, "r1", "bob")
        check.equal(kc.requests_to("POST")[0].json["username"], "bob")


class TestSetUserPassword:
    """set_user_password。"""

    URL = f"{R1}/users/u1/reset-password"

    @pytest.mark.parametrize("temporary", [False, True])
    def test_payload(self, kc, temporary):
        """type=password / temporary / value を PUT する(204 を期待)。"""
        kc.on("PUT", self.URL, status=204)
        set_user_password(kc.admin, "r1", "u1", "NewP@ss1", temporary=temporary)
        check.equal(kc.requests_to("PUT")[0].json, {"type": "password", "temporary": temporary, "value": "NewP@ss1"})

    def test_default_is_not_temporary(self, kc):
        """temporary の既定は False。"""
        kc.on("PUT", self.URL, status=204)
        set_user_password(kc.admin, "r1", "u1", "x")
        check.is_false(kc.requests_to("PUT")[0].json["temporary"])

    def test_failure_does_not_expose_password(self, kc, caplog):
        """パスワードポリシー違反の例外・ログにパスワードが出ない。"""
        kc.on("PUT", self.URL, httpx.Response(400, json={"error": "invalidPasswordMinLengthMessage", "errorMessage": "Invalid password: minimum length 8."}))
        with caplog.at_level("DEBUG"):
            with pytest.raises(KeycloakAdminError) as exc_info:
                set_user_password(kc.admin, "r1", "u1", "short-Pw1", temporary=True)
        check.equal(exc_info.value.status_code, 400)
        check.is_in("minimum length", exc_info.value.detail)
        check.is_not_in("short-Pw1", str(exc_info.value))
        check.is_not_in("short-Pw1", caplog.text)

    def test_success_log_does_not_expose_password(self, kc, caplog):
        """成功時のログにもパスワードが出ない。"""
        kc.on("PUT", self.URL, status=204)
        with caplog.at_level("DEBUG"):
            set_user_password(kc.admin, "r1", "u1", "visible-Pw1")
        check.is_not_in("visible-Pw1", caplog.text)
