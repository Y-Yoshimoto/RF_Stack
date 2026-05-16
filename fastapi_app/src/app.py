#!/usr/bin/env python
# coding:utf-8
import base64
import json
import os
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import Cookie, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

# サブモジュール読み込み
from rest_sample.apiapp import router as RestSample
# from proxy.apiapp import router as proxy
from control_plane_app.apiapp import router as router_control_plane

# アプリケーション起動
app = FastAPI()
# サブモジュール読み込み
# 参考: https://fastapi.tiangolo.com/tutorial/bigger-applications/#import-fastapi
app.include_router(RestSample)
# コントロールプレーン
app.include_router(
    router_control_plane,
    prefix="/control_plane",
    tags=["control_plane"],
)

KEYCLOAK_INTERNAL_BASE_URL = os.getenv("KEYCLOAK_INTERNAL_BASE_URL", "http://keycloak_c:8080/keycloak").rstrip("/")
KEYCLOAK_PUBLIC_BASE_URL = os.getenv("KEYCLOAK_PUBLIC_BASE_URL", "/keycloak").rstrip("/")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "rf-stack-client")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET")
KEYCLOAK_REDIRECT_URI = os.getenv("KEYCLOAK_REDIRECT_URI", "http://localhost:5173/api/auth/callback")
KEYCLOAK_LOGOUT_REDIRECT_URI = os.getenv("KEYCLOAK_LOGOUT_REDIRECT_URI", "http://localhost:5173/login")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "rf_session_id")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))

# NOTE: 開発用のインメモリストア。再起動で消えるため本番では永続ストアに置き換える。
auth_session_store: dict[str, dict] = {}
auth_pending_state_store: dict[str, dict] = {}
auth_store_lock = threading.Lock()
AUTH_PENDING_STATE_TTL_SECONDS = int(os.getenv("AUTH_PENDING_STATE_TTL_SECONDS", "300"))


def _encode_query(query: dict) -> str:
    return urlencode({k: v for k, v in query.items() if v is not None})


def _decode_jwt_payload(token: str | None) -> dict:
    if not token:
        return {}
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
    except Exception:
        return {}


def _exchange_authorization_code(code: str) -> dict:
    token_url = f"{KEYCLOAK_INTERNAL_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    form_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": KEYCLOAK_REDIRECT_URI,
        "client_id": KEYCLOAK_CLIENT_ID,
    }
    if KEYCLOAK_CLIENT_SECRET:
        form_data["client_secret"] = KEYCLOAK_CLIENT_SECRET

    response = httpx.post(token_url, data=form_data, timeout=10.0)
    response.raise_for_status()
    return response.json()


def _cleanup_expired_sessions() -> None:
    now = int(time.time())
    for session_id in list(auth_session_store.keys()):
        if auth_session_store[session_id].get("expires_at", 0) <= now:
            auth_session_store.pop(session_id, None)


def _cleanup_expired_pending_states() -> None:
    now = int(time.time())
    for state in list(auth_pending_state_store.keys()):
        if (now - auth_pending_state_store[state].get("created_at", now)) > AUTH_PENDING_STATE_TTL_SECONDS:
            auth_pending_state_store.pop(state, None)


def _build_keycloak_login_url(state: str, nonce: str) -> str:
    auth_url = f"{KEYCLOAK_PUBLIC_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth"
    query = {
        "client_id": KEYCLOAK_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": KEYCLOAK_REDIRECT_URI,
        "state": state,
        "nonce": nonce,
    }
    return f"{auth_url}?{_encode_query(query)}"



@app.get("/", include_in_schema=False)
def read_root():
    return {"Path": "root"}


@app.get("/api/auth/login", include_in_schema=False)
def auth_login(redirect_path: str = Query(default="/")):
    with auth_store_lock:
        _cleanup_expired_pending_states()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    with auth_store_lock:
        auth_pending_state_store[state] = {
            "created_at": int(time.time()),
            "redirect_path": redirect_path if redirect_path.startswith("/") else "/",
        }
    return RedirectResponse(url=_build_keycloak_login_url(state=state, nonce=nonce), status_code=302)


@app.get("/api/auth/callback", include_in_schema=False)
def auth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=401, detail=error)
    if not code or not state:
        raise HTTPException(status_code=400, detail="code and state are required")

    with auth_store_lock:
        _cleanup_expired_pending_states()
        state_data = auth_pending_state_store.pop(state, None)
    if not state_data:
        raise HTTPException(status_code=400, detail="invalid state")

    try:
        token_data = _exchange_authorization_code(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="token exchange failed") from exc

    expires_in = int(token_data.get("expires_in", SESSION_TTL_SECONDS))
    session_id = secrets.token_urlsafe(32)
    with auth_store_lock:
        auth_session_store[session_id] = {
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + expires_in,
            "token_data": token_data,
        }
        _cleanup_expired_sessions()

    response = RedirectResponse(url=state_data["redirect_path"], status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=expires_in,
        httponly=True,
        secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        samesite=os.getenv("SESSION_COOKIE_SAMESITE", "lax"),
        path="/",
    )
    return response


@app.get("/api/auth/session", include_in_schema=False)
def auth_session(session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    with auth_store_lock:
        _cleanup_expired_sessions()
    if not session_id:
        return JSONResponse({"isAuthN": False, "user": None, "roles": [], "permissions": []})

    with auth_store_lock:
        session_data = auth_session_store.get(session_id)
    if not session_data:
        return JSONResponse({"isAuthN": False, "user": None, "roles": [], "permissions": []})

    payload = _decode_jwt_payload(session_data.get("token_data", {}).get("access_token"))
    roles = payload.get("realm_access", {}).get("roles", []) if isinstance(payload.get("realm_access"), dict) else []
    return JSONResponse({
        "isAuthN": True,
        "user": payload.get("preferred_username"),
        "roles": roles if isinstance(roles, list) else [],
        "permissions": [],
    })


@app.post("/api/auth/logout", include_in_schema=False)
def auth_logout(session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    if session_id:
        with auth_store_lock:
            auth_session_store.pop(session_id, None)

    response = JSONResponse({"message": "Logged out"})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response


@app.post("/api/login", include_in_schema=False)
def login():
    return {"message": "Use /api/auth/login for Keycloak authentication"}

def main():
    # サーバー起動
    uvicorn.run(app=app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
