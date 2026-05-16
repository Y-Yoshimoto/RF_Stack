import base64
import json
import os
import sys
import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


os.environ.setdefault("APP_DB_USER", "app_db_user")
os.environ.setdefault("APP_DB_PASSWORD", "app_db_password")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("CONTROL_PLANE_DB_NAME", "control_plane_db")

sys.path.append(os.path.abspath("./src"))
import app as app_module  # noqa: E402


def _create_jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"header.{encoded}.signature"


def test_auth_login_redirects_to_keycloak():
    client = TestClient(app_module.app)
    response = client.get("/api/auth/login?redirect_path=/button", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert "/keycloak/realms/" in location
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [app_module.KEYCLOAK_REDIRECT_URI]
    assert query["state"][0]


def test_auth_callback_sets_cookie_and_auth_session(monkeypatch):
    client = TestClient(app_module.app)
    login_response = client.get("/api/auth/login?redirect_path=/button", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    def _mock_exchange_authorization_code(_: str) -> dict:
        return {
            "access_token": _create_jwt(
                {
                    "preferred_username": "test-user",
                    "realm_access": {"roles": ["user", "viewer"]},
                    "exp": int(time.time()) + 600,
                }
            ),
            "expires_in": 600,
        }

    monkeypatch.setattr(app_module, "_exchange_authorization_code", _mock_exchange_authorization_code)
    callback_response = client.get(f"/api/auth/callback?code=dummy-code&state={state}", follow_redirects=False)

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/button"
    assert app_module.SESSION_COOKIE_NAME in callback_response.headers.get("set-cookie", "")

    session_id = callback_response.cookies.get(app_module.SESSION_COOKIE_NAME)
    client.cookies.set(app_module.SESSION_COOKIE_NAME, session_id)
    session_response = client.get("/api/auth/session")
    session_json = session_response.json()
    assert session_json["isAuthN"] is True
    assert session_json["user"] == "test-user"
    assert session_json["roles"] == ["user", "viewer"]
