# -*- coding: utf-8 -*-
"""modules.auth.login.build_login_session(ログイン完了時のトークン検証とセッション内容)のテスト。

署名鍵はテスト内で生成した RSA 鍵。JWKS の取得はスタブに差し替える(Keycloak には接続しない)。
"""
import time

import jwt
import pytest
import pytest_check as check
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from modules.auth import token
from modules.auth.login import LOGIN_REJECTED_DETAIL, build_login_session
from modules.auth.plane import Plane

TENANT_ID = "0194e6a0-0000-7000-8000-00000000a1fa"
NONCE = "expected-nonce"


class StubJwks:
    """JWKS 取得を行わず、固定の公開鍵を返すスタブ。"""

    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        return type("SigningKey", (), {"key": self._key})()


@pytest.fixture(scope="module")
def private_key():
    """このモジュールで共有する RSA 鍵(生成が遅いので 1 回だけ)。"""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _stub_jwks(monkeypatch, private_key):
    """JWKS の取得をスタブに差し替える。"""
    monkeypatch.setattr(token, "_jwks_client", lambda _uri: StubJwks(private_key.public_key()))


class Issuer:
    """設定に沿った id_token / access token / トークンレスポンスを発行するテスト用ヘルパー。"""

    def __init__(self, config, private_key, plane: Plane, realm: str):
        self.config, self.key, self.plane, self.realm = config, private_key, plane, realm
        self.client_id = config.client_id_for(plane)

    def _claims(self, **overrides):
        now = int(time.time())
        claims = {"iss": self.config.build_issuer(self.config.kc_internal_base, self.realm), "sub": "user-1", "iat": now - 5, "exp": now + 300}
        claims.update(overrides)
        return claims

    def id_token(self, **overrides) -> str:
        claims = self._claims(aud=self.client_id, nonce=NONCE, preferred_username="tester", email="tester@example.com")
        claims.update(overrides)
        return jwt.encode({k: v for k, v in claims.items() if v is not None}, self.key, algorithm="RS256")

    def access_token(self, roles=(), **overrides) -> str:
        claims = self._claims(azp=self.client_id, realm_access={"roles": list(roles)})
        claims.update(overrides)
        return jwt.encode({k: v for k, v in claims.items() if v is not None}, self.key, algorithm="RS256")

    def response(self, *, roles=(), id_overrides=None, access_overrides=None, **extra):
        data = {
            "access_token": self.access_token(roles, **(access_overrides or {})),
            "refresh_token": "refresh-token",
            "id_token": self.id_token(**(id_overrides or {})),
            "expires_in": 300,
            "refresh_expires_in": 1800,
        }
        data.update(extra)
        return data


@pytest.fixture
def app_issuer(config, private_key) -> Issuer:
    return Issuer(config, private_key, Plane.APP, "tenant-alpha")


@pytest.fixture
def cp_issuer(config, private_key) -> Issuer:
    return Issuer(config, private_key, Plane.CP, "control-plane")


def _login_app(config, issuer, response, **kwargs):
    defaults = {"expected_nonce": NONCE, "tenant_code": "alpha", "expected_tenant_id": TENANT_ID}
    defaults.update(kwargs)
    return build_login_session(config, Plane.APP, "tenant-alpha", response, **defaults)


def _login_cp(config, response, **kwargs):
    kwargs.setdefault("expected_nonce", NONCE)
    return build_login_session(config, Plane.CP, "control-plane", response, **kwargs)


def _status_of(exc_info) -> tuple[int, str]:
    return exc_info.value.status_code, exc_info.value.detail


class TestAppLogin:
    """AP のログイン。"""

    def test_success_builds_session(self, config, app_issuer):
        """正しいトークンから、プレーン・レルム・テナント・ロール(許可リストのみ)・トークン記録を持つセッションを作る。"""
        response = app_issuer.response(roles=["offline_access", "uma_authorization", "default-roles-tenant-alpha", "tenant_admin", "member", "saas_admin"], id_overrides={"tenant_id": TENANT_ID})
        session_data = _login_app(config, app_issuer, response)
        check.equal(session_data["plane"], "app")
        check.equal(session_data["realm"], "tenant-alpha")
        check.equal((session_data["tenant_id"], session_data["tenant_code"]), (TENANT_ID, "alpha"))
        check.equal(session_data["user"]["roles"], ["member", "tenant_admin"], "既定ロールと CP のロールは載せない")
        check.equal(session_data["user"]["plane"], "app")
        check.equal(session_data["user"]["tenant_id"], TENANT_ID)
        check.equal((session_data["user"]["sub"], session_data["user"]["preferred_username"], session_data["user"]["email"]), ("user-1", "tester", "tester@example.com"))
        check.equal(session_data["tokens"]["refresh_token"], "refresh-token")
        check.is_in("access_token_expires_at", session_data["tokens"])

    def test_tenant_id_claim_may_come_from_access_token(self, config, app_issuer):
        """tenant_id クレームは id_token に無ければ access token から読む。"""
        response = app_issuer.response(roles=["member"], access_overrides={"tenant_id": TENANT_ID})
        check.equal(_login_app(config, app_issuer, response)["tenant_id"], TENANT_ID)

    def test_tenant_id_comparison_tolerates_notation(self, config, app_issuer):
        """tenant_id の比較は UUID として行い、大文字・小文字の表記揺れを許す。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID.upper()})
        session_data = _login_app(config, app_issuer, response)
        check.equal(session_data["tenant_id"], TENANT_ID, "セッションにはレジストリ上の値を保存する")

    @pytest.mark.parametrize(
        "claim",
        [None, "", "not-a-uuid", "0194e6a0-0000-7000-8000-00000000ffff", 12345, ["x"]],
        ids=["absent", "empty", "not-uuid", "other-tenant", "number", "list"],
    )
    def test_tenant_id_mismatch_is_rejected_with_uniform_detail(self, config, app_issuer, claim):
        """tenant_id クレームが無い・別テナント・不正な値は 403 で、理由を区別しない同一の detail を返す。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": claim})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(_status_of(exc_info), (403, LOGIN_REJECTED_DETAIL))

    def test_without_expected_tenant_id_the_claim_is_used(self, config, app_issuer):
        """expected_tenant_id を渡さない場合(開発用ログイン)は一致を確認せず、クレームの値を使う。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID})
        session_data = _login_app(config, app_issuer, response, expected_tenant_id=None)
        check.equal(session_data["tenant_id"], TENANT_ID)

    @pytest.mark.parametrize("field", ["access_token", "refresh_token", "id_token"])
    def test_missing_tokens_are_401(self, config, app_issuer, field):
        """トークンレスポンスにトークンが欠けていれば 401(Invalid token response)。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID})
        response.pop(field)
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(_status_of(exc_info), (401, "Invalid token response"))

    def test_nonce_mismatch_is_401(self, config, app_issuer):
        """nonce が認可リクエスト時と違えば 401(Invalid token)。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID, "nonce": "tampered"})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(_status_of(exc_info), (401, "Invalid token"))

    def test_id_token_for_another_client_is_401(self, config, app_issuer):
        """aud が AP のクライアントでない id_token(CP のクライアント向けなど)は 401。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID, "aud": config.cp_client_id})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(exc_info.value.status_code, 401)

    def test_access_token_for_another_client_is_401(self, config, app_issuer):
        """azp が AP のクライアントでない access token は 401。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID}, access_overrides={"azp": "other-client"})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(exc_info.value.status_code, 401)

    def test_token_from_another_realm_is_401(self, config, app_issuer):
        """別レルムが発行した(issuer が違う)トークンは 401。"""
        other_issuer = config.build_issuer(config.kc_internal_base, "tenant-beta")
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID, "iss": other_issuer})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(exc_info.value.status_code, 401)

    def test_subject_mismatch_between_tokens_is_401(self, config, app_issuer):
        """id_token と access token の sub が食い違えば 401。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID}, access_overrides={"sub": "someone-else"})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(_status_of(exc_info), (401, "Invalid token"))

    def test_expired_token_is_401(self, config, app_issuer):
        """期限切れのトークンは 401。"""
        response = app_issuer.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID, "exp": int(time.time()) - 100})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(exc_info.value.status_code, 401)

    def test_token_signed_with_other_key_is_401(self, config, app_issuer):
        """別の鍵で署名されたトークンは 401。"""
        other = Issuer(config, rsa.generate_private_key(public_exponent=65537, key_size=2048), Plane.APP, "tenant-alpha")
        response = other.response(roles=["member"], id_overrides={"tenant_id": TENANT_ID})
        with pytest.raises(HTTPException) as exc_info:
            _login_app(config, app_issuer, response)
        check.equal(exc_info.value.status_code, 401)


class TestCpLogin:
    """CP のログイン。"""

    def test_success(self, config, cp_issuer):
        """control-plane レルムで saas_admin / saas_viewer を持てばセッションを作る。テナント情報は載らない。"""
        session_data = _login_cp(config, cp_issuer.response(roles=["saas_viewer", "member", "tenant_admin", "offline_access"]))
        check.equal((session_data["plane"], session_data["realm"]), ("cp", "control-plane"))
        check.equal(session_data["user"]["roles"], ["saas_viewer"], "AP のロール名は載せない")
        check.equal(session_data["user"]["plane"], "cp")
        check.is_not_in("tenant_id", session_data)
        check.is_not_in("tenant_code", session_data)
        check.is_not_in("tenant_id", session_data["user"])

    @pytest.mark.parametrize("roles", [[], ["tenant_admin"], ["member"], ["offline_access", "uma_authorization"]])
    def test_without_cp_role_is_rejected(self, config, cp_issuer, roles):
        """CP のロールを一つも持たないユーザー(AP のロールのみを含む)は 403(Login rejected)。"""
        with pytest.raises(HTTPException) as exc_info:
            _login_cp(config, cp_issuer.response(roles=roles))
        check.equal(_status_of(exc_info), (403, LOGIN_REJECTED_DETAIL))

    @pytest.mark.parametrize("realm", ["tenant-alpha", "master", "Control-Plane", "control-plane2"])
    def test_realm_other_than_control_plane_is_rejected_before_verification(self, config, private_key, realm):
        """control-plane 以外のレルムでの CP ログインは、トークンの検証より前に 403 で拒否する(テナントのユーザーが CP に入れない)。"""
        issuer = Issuer(config, private_key, Plane.CP, realm)
        with pytest.raises(HTTPException) as exc_info:
            build_login_session(config, Plane.CP, realm, issuer.response(roles=["saas_admin"]), expected_nonce=NONCE)
        check.equal(_status_of(exc_info), (403, LOGIN_REJECTED_DETAIL))

    def test_cp_token_must_target_the_cp_client(self, config, cp_issuer):
        """CP のログインで、AP のクライアント向けに発行されたトークンは 401。"""
        response = cp_issuer.response(roles=["saas_admin"], id_overrides={"aud": config.client_id})
        with pytest.raises(HTTPException) as exc_info:
            _login_cp(config, response)
        check.equal(exc_info.value.status_code, 401)

    def test_rejection_details_are_uniform(self, config, cp_issuer, private_key):
        """ロール不足とレルム違いで、detail は同一(理由を区別しない)。"""
        with pytest.raises(HTTPException) as no_role:
            _login_cp(config, cp_issuer.response(roles=[]))
        issuer = Issuer(config, private_key, Plane.CP, "tenant-alpha")
        with pytest.raises(HTTPException) as wrong_realm:
            build_login_session(config, Plane.CP, "tenant-alpha", issuer.response(roles=["saas_admin"]), expected_nonce=NONCE)
        check.equal(_status_of(no_role), _status_of(wrong_realm))
