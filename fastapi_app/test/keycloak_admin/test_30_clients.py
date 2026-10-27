# -*- coding: utf-8 -*-
"""clients(クライアント・シークレット・プロトコルマッパー)のテスト。"""
import json as jsonlib

import httpx
import pytest
import pytest_check as check

from modules.keycloak_admin import (
    ClientSpec,
    KeycloakAdminError,
    ProtocolMapperSpec,
    audience_mapper,
    ensure_client,
    ensure_protocol_mapper,
    find_client,
    get_client_secret,
    hardcoded_claim_mapper,
)
from modules.keycloak_admin.clients import list_protocol_mappers

C = "/keycloak/admin/realms/r1/clients"
SPEC = ClientSpec(client_id="fastapi-app", redirect_uris=("http://app/cb",), web_origins=("http://app",), post_logout_redirect_uris=("http://app/*",))


class TestFindClient:
    """find_client。"""

    def test_query_and_match(self, kc):
        """clientId で検索し、clientId が一致するものだけを返す。"""
        kc.on("GET", C, json=[{"id": "x", "clientId": "other"}, {"id": "y", "clientId": "fastapi-app"}])
        check.equal(find_client(kc.admin, "r1", "fastapi-app"), {"id": "y", "clientId": "fastapi-app"})
        check.equal(kc.api_requests[0].query, {"clientId": "fastapi-app"})

    @pytest.mark.parametrize("body", [[], [{"id": "x", "clientId": "other"}], [{"id": "x", "clientId": "FASTAPI-APP"}]])
    def test_not_found(self, kc, body):
        """空や、clientId が完全一致しないもの(大文字小文字は区別する)は None。"""
        kc.on("GET", C, json=body)
        check.is_none(find_client(kc.admin, "r1", "fastapi-app"))


class TestEnsureClient:
    """ensure_client の分岐。"""

    def test_create_with_location(self, kc):
        """無ければ POST し、Location から内部 ID を得る(追加の検索なし)。"""
        kc.on("GET", C, json=[])
        kc.on("POST", C, httpx.Response(201, headers={"Location": f"http://kc{C}/internal-1"}))
        result = ensure_client(kc.admin, "r1", SPEC)
        check.equal((result.id, result.client_id, result.created, result.updated), ("internal-1", "fastapi-app", True, False))
        check.equal(kc.requests_to("POST", C)[0].json, SPEC.to_representation())
        check.equal(kc.requests_to("PUT"), [])
        check.equal(len(kc.requests_to("GET")), 1)

    def test_create_without_location_searches_again(self, kc):
        """Location が無ければ検索し直して内部 ID を得る。"""
        kc.on("GET", C, httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": "internal-2", "clientId": "fastapi-app"}]))
        kc.on("POST", C, status=201)
        result = ensure_client(kc.admin, "r1", SPEC)
        check.equal((result.id, result.created), ("internal-2", True))

    def test_create_without_location_and_not_found_raises(self, kc):
        """Location が無く検索しても見つからなければ KeycloakAdminError。"""
        kc.on("GET", C, json=[])
        kc.on("POST", C, status=201)
        with pytest.raises(KeycloakAdminError, match="resolve client internal id"):
            ensure_client(kc.admin, "r1", SPEC)

    def test_existing_is_updated_by_default(self, kc):
        """既存は既定で PUT し直す(updated=True、created=False)。ID は既存のもの。"""
        kc.on("GET", C, json=[{"id": "internal-3", "clientId": "fastapi-app"}])
        kc.on("PUT", f"{C}/internal-3", status=204)
        result = ensure_client(kc.admin, "r1", SPEC)
        check.equal((result.id, result.created, result.updated), ("internal-3", False, True))
        check.equal(kc.requests_to("PUT")[0].json, SPEC.to_representation())
        check.equal(kc.requests_to("POST"), [])

    def test_existing_not_updated_when_disabled(self, kc):
        """update_existing=False なら PUT せず、書き込みはゼロ。"""
        kc.on("GET", C, json=[{"id": "internal-3", "clientId": "fastapi-app"}])
        result = ensure_client(kc.admin, "r1", SPEC, update_existing=False)
        check.equal((result.id, result.created, result.updated), ("internal-3", False, False))
        check.equal(kc.writes, [])

    def test_conflict_on_create_resolves_existing_and_updates(self, kc):
        """作成時 409 なら検索し直して既存扱いにし、既定では PUT する。"""
        kc.on("GET", C, httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": "internal-4", "clientId": "fastapi-app"}]))
        kc.on("POST", C, status=409)
        kc.on("PUT", f"{C}/internal-4", status=204)
        result = ensure_client(kc.admin, "r1", SPEC)
        check.equal((result.id, result.created, result.updated), ("internal-4", False, True))

    def test_conflict_on_create_without_update(self, kc):
        """作成時 409 で update_existing=False なら PUT しない。"""
        kc.on("GET", C, httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": "internal-4", "clientId": "fastapi-app"}]))
        kc.on("POST", C, status=409)
        result = ensure_client(kc.admin, "r1", SPEC, update_existing=False)
        check.equal((result.created, result.updated), (False, False))
        check.equal(kc.requests_to("PUT"), [])

    def test_conflict_and_not_found_raises(self, kc):
        """作成時 409 なのに見つからなければ KeycloakAdminError。"""
        kc.on("GET", C, json=[])
        kc.on("POST", C, status=409)
        with pytest.raises(KeycloakAdminError, match="resolve client internal id"):
            ensure_client(kc.admin, "r1", SPEC)

    def test_create_failure_raises(self, kc):
        """作成が 201/409 以外なら例外。"""
        kc.on("GET", C, json=[])
        kc.on("POST", C, status=403)
        with pytest.raises(KeycloakAdminError, match="create client fastapi-app"):
            ensure_client(kc.admin, "r1", SPEC)

    def test_update_failure_raises(self, kc):
        """更新が 204 以外なら例外。"""
        kc.on("GET", C, json=[{"id": "i", "clientId": "fastapi-app"}])
        kc.on("PUT", f"{C}/i", status=400, json={"errorMessage": "bad"})
        with pytest.raises(KeycloakAdminError, match="update client"):
            ensure_client(kc.admin, "r1", SPEC)


class TestClientSecret:
    """get_client_secret。"""

    URL = f"{C}/internal-1/client-secret"

    def test_returns_value(self, kc):
        """value を返す。"""
        kc.on("GET", self.URL, json={"type": "secret", "value": "s3cr3t"})
        check.equal(get_client_secret(kc.admin, "r1", "internal-1"), "s3cr3t")

    @pytest.mark.parametrize("body", [{"value": ""}, {"value": None}, {}, ["x"], None])
    def test_empty_secret_raises_without_leaking(self, kc, body):
        """value が空・無し・辞書でない(public クライアント等)なら KeycloakAdminError。"""
        kc.on("GET", self.URL, httpx.Response(200, content=jsonlib.dumps(body), headers={"content-type": "application/json"}))
        with pytest.raises(KeycloakAdminError, match="client secret is empty"):
            get_client_secret(kc.admin, "r1", "internal-1")

    def test_http_failure_raises(self, kc):
        """取得失敗(404 など)は例外。"""
        kc.on("GET", self.URL, status=404)
        with pytest.raises(KeycloakAdminError) as exc_info:
            get_client_secret(kc.admin, "r1", "internal-1")
        check.equal(exc_info.value.status_code, 404)


class TestEnsureProtocolMapper:
    """ensure_protocol_mapper の分岐。"""

    M = f"{C}/cid/protocol-mappers/models"
    SPEC = hardcoded_claim_mapper("tenant_id", "tenant_id", "T-1")

    def test_list_none_is_empty(self, kc):
        """一覧が null なら空リスト。"""
        kc.on("GET", self.M, httpx.Response(200, content=b"null", headers={"content-type": "application/json"}))
        check.equal(list_protocol_mappers(kc.admin, "r1", "cid"), [])

    def test_create_with_location(self, kc):
        """無ければ POST(201 のみ期待)し、Location から id を得る。"""
        kc.on("GET", self.M, json=[])
        kc.on("POST", self.M, httpx.Response(201, headers={"Location": f"http://kc{self.M}/m-1"}))
        result = ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)
        check.equal((result.id, result.name, result.created, result.updated), ("m-1", "tenant_id", True, False))
        check.equal(kc.requests_to("POST")[0].json, self.SPEC.to_representation())

    def test_create_without_location_lists_again(self, kc):
        """Location が無ければ一覧を取り直して id を得る。"""
        kc.on("GET", self.M, httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": "m-2", "name": "tenant_id"}]))
        kc.on("POST", self.M, status=201)
        result = ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)
        check.equal((result.id, result.created), ("m-2", True))

    def test_create_without_location_and_not_found_raises(self, kc):
        """作成後に一覧にも無ければ KeycloakAdminError。"""
        kc.on("GET", self.M, json=[])
        kc.on("POST", self.M, status=201)
        with pytest.raises(KeycloakAdminError, match="resolve protocol mapper id"):
            ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)

    def test_existing_identical_makes_no_writes(self, kc):
        """設定が一致していれば PUT しない(created=False, updated=False)。"""
        existing = {"id": "m-3", **self.SPEC.to_representation()}
        kc.on("GET", self.M, json=[existing])
        result = ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)
        check.equal((result.id, result.created, result.updated), ("m-3", False, False))
        check.equal(kc.writes, [])

    def test_existing_with_extra_config_keys_counts_as_identical(self, kc):
        """既存に余分な config キーがあっても、指定したキーが一致すれば差分なし(部分集合で比較)。"""
        existing = {"id": "m-3", **self.SPEC.to_representation()}
        existing["config"] = {**existing["config"], "user.attribute": "kept"}
        kc.on("GET", self.M, json=[existing])
        check.is_false(ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC).updated)
        check.equal(kc.writes, [])

    def test_existing_with_different_config_is_put(self, kc):
        """config の値が違えば PUT し(ボディに id を含める)、updated=True。"""
        existing = {"id": "m-4", **self.SPEC.to_representation()}
        existing["config"] = {**existing["config"], "claim.value": "OLD"}
        kc.on("GET", self.M, json=[existing])
        kc.on("PUT", f"{self.M}/m-4", status=204)
        result = ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)
        check.equal((result.id, result.created, result.updated), ("m-4", False, True))
        check.equal(kc.requests_to("PUT")[0].json, {**self.SPEC.to_representation(), "id": "m-4"})

    def test_existing_with_missing_config_key_is_put(self, kc):
        """既存に指定キーが無ければ差分ありとして PUT する。"""
        existing = {"id": "m-5", **self.SPEC.to_representation()}
        existing["config"] = {}
        kc.on("GET", self.M, json=[existing])
        kc.on("PUT", f"{self.M}/m-5", status=204)
        check.is_true(ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC).updated)

    def test_existing_with_different_type_is_put(self, kc):
        """マッパー種別が違えば PUT する。"""
        existing = {"id": "m-6", **self.SPEC.to_representation(), "protocolMapper": "oidc-usermodel-property-mapper"}
        kc.on("GET", self.M, json=[existing])
        kc.on("PUT", f"{self.M}/m-6", status=204)
        check.is_true(ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC).updated)

    def test_mapper_identified_by_name(self, kc):
        """同じクライアントの別名マッパーは無視し、name で同定する。"""
        other = {"id": "o", **audience_mapper("aud", "fastapi-app").to_representation()}
        kc.on("GET", self.M, json=[other])
        kc.on("POST", self.M, httpx.Response(201, headers={"Location": f"{self.M}/new"}))
        result = ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)
        check.equal((result.id, result.created), ("new", True))

    def test_conflict_on_create_is_treated_as_existing(self, kc):
        """作成時 409(並行実行)なら、他の ensure_* と同様に既存扱いで収束する。"""
        existing = {"id": "m-7", **self.SPEC.to_representation()}
        kc.on("GET", self.M, httpx.Response(200, json=[]), httpx.Response(200, json=[existing]))
        kc.on("POST", self.M, status=409)
        result = ensure_protocol_mapper(kc.admin, "r1", "cid", self.SPEC)
        check.equal((result.id, result.created), ("m-7", False))


class TestMapperFactories:
    """hardcoded_claim_mapper / audience_mapper が組み立てる設定。"""

    def test_hardcoded_claim_defaults(self):
        """既定: 固定値クレームを id/access/userinfo/introspection のすべてに出す。値はすべて文字列。"""
        spec = hardcoded_claim_mapper("tenant_id", "tenant_id", "T-1")
        check.equal(spec.protocol_mapper, "oidc-hardcoded-claim-mapper")
        check.equal(spec.protocol, "openid-connect")
        check.equal(
            dict(spec.config),
            {
                "claim.name": "tenant_id",
                "claim.value": "T-1",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
                "introspection.token.claim": "true",
            },
        )
        check.is_true(all(isinstance(v, str) for v in spec.config.values()))

    def test_hardcoded_claim_flags(self):
        """フラグ指定は小文字の "true"/"false" 文字列になる。"""
        spec = hardcoded_claim_mapper("n", "c", "v", json_type="int", id_token=False, access_token=False, userinfo=False)
        check.equal(spec.config["jsonType.label"], "int")
        check.equal([spec.config[k] for k in ("id.token.claim", "access.token.claim", "userinfo.token.claim")], ["false", "false", "false"])

    def test_audience_mapper(self):
        """Audience マッパーは access_token のみに既定で出す。"""
        spec = audience_mapper("aud", "fastapi-app")
        check.equal(spec.protocol_mapper, "oidc-audience-mapper")
        check.equal(
            dict(spec.config),
            {"included.client.audience": "fastapi-app", "id.token.claim": "false", "access.token.claim": "true", "introspection.token.claim": "true"},
        )
        check.equal(audience_mapper("aud", "x", id_token=True, access_token=False).config["id.token.claim"], "true")

    def test_spec_is_hashable_frozen(self):
        """ProtocolMapperSpec は不変。"""
        spec = ProtocolMapperSpec(name="n", protocol_mapper="p")
        with pytest.raises(AttributeError):
            spec.name = "x"  # type: ignore[misc]
