#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash keycloak_c/setup_realm_client_user.sh <realm_name> <client_id> <username> [user_password]

Arguments:
  realm_name     Realm name to create/update (tenant)
  client_id      Client ID to create/update
  username       Username to create/update
  user_password  Optional. Default: KEYCLOAK_INIT_USER_PASSWORD or "ChangeMe123!"

Environment variables:
  KEYCLOAK_BASE_URL                 default: http://localhost:8080
  KEYCLOAK_HTTP_RELATIVE_PATH       default: keycloak
  KEYCLOAK_ADMIN_USERNAME           default: admin
  KEYCLOAK_ADMIN_PASSWORD           default: admin
  APP_CALLBACK_URL                  default: http://localhost:5173/api/auth/callback
  APP_POST_LOGOUT_REDIRECT_URI      default: http://localhost:5173/*
  APP_WEB_ORIGIN                    default: http://localhost:5173
  KEYCLOAK_INIT_USER_PASSWORD       default for user_password when arg omitted
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 3 ]]; then
  usage
  exit 1
fi

REALM_NAME="$1"
CLIENT_ID="$2"
USERNAME="$3"
USER_PASSWORD="${4:-${KEYCLOAK_INIT_USER_PASSWORD:-ChangeMe123!}}"

KEYCLOAK_BASE_URL="${KEYCLOAK_BASE_URL:-http://localhost:8080}"
KEYCLOAK_HTTP_RELATIVE_PATH="${KEYCLOAK_HTTP_RELATIVE_PATH:-keycloak}"
KEYCLOAK_ADMIN_USERNAME="${KEYCLOAK_ADMIN_USERNAME:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
APP_CALLBACK_URL="${APP_CALLBACK_URL:-http://localhost:5173/api/auth/callback}"
APP_POST_LOGOUT_REDIRECT_URI="${APP_POST_LOGOUT_REDIRECT_URI:-http://localhost:5173/*}"
APP_WEB_ORIGIN="${APP_WEB_ORIGIN:-http://localhost:5173}"

KC_BASE="${KEYCLOAK_BASE_URL%/}/${KEYCLOAK_HTTP_RELATIVE_PATH#/}"
TOKEN_URL="${KC_BASE}/realms/master/protocol/openid-connect/token"
ADMIN_REALMS_URL="${KC_BASE}/admin/realms"

TMP_BODY="$(mktemp)"
trap 'rm -f "$TMP_BODY"' EXIT

http_call() {
  # http_call <METHOD> <URL> [DATA_JSON]
  local method="$1"
  local url="$2"
  local data="${3:-}"
  local status

  if [[ -n "$data" ]]; then
    status="$(curl -sS -o "$TMP_BODY" -w "%{http_code}" -X "$method" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      -H "Content-Type: application/json" \
      "$url" \
      --data "$data")"
  else
    status="$(curl -sS -o "$TMP_BODY" -w "%{http_code}" -X "$method" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      "$url")"
  fi

  echo "$status"
}

json_extract() {
  local expr="$1"
  python3 -c "import json,sys; data=json.load(sys.stdin); print(${expr})"
}

echo "[1/6] Get admin access token"
TOKEN_RESP="$(curl -sS -X POST "$TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=admin-cli" \
  --data-urlencode "username=${KEYCLOAK_ADMIN_USERNAME}" \
  --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}")"

ADMIN_TOKEN="$(printf '%s' "$TOKEN_RESP" | json_extract "data.get('access_token','')")"
if [[ -z "$ADMIN_TOKEN" ]]; then
  echo "ERROR: Failed to obtain admin token."
  echo "$TOKEN_RESP"
  exit 1
fi

echo "[2/6] Ensure realm exists: ${REALM_NAME}"
REALM_STATUS="$(http_call GET "${ADMIN_REALMS_URL}/${REALM_NAME}")"
if [[ "$REALM_STATUS" == "404" ]]; then
  CREATE_REALM_PAYLOAD="$(cat <<JSON
{"realm":"${REALM_NAME}","enabled":true}
JSON
)"
  CREATE_REALM_STATUS="$(http_call POST "${ADMIN_REALMS_URL}" "$CREATE_REALM_PAYLOAD")"
  if [[ "$CREATE_REALM_STATUS" != "201" ]]; then
    echo "ERROR: Failed to create realm. HTTP ${CREATE_REALM_STATUS}"
    cat "$TMP_BODY"
    exit 1
  fi
  echo "  - Realm created"
elif [[ "$REALM_STATUS" == "200" ]]; then
  echo "  - Realm already exists"
else
  echo "ERROR: Failed to query realm. HTTP ${REALM_STATUS}"
  cat "$TMP_BODY"
  exit 1
fi

echo "[3/6] Ensure client exists: ${CLIENT_ID}"
CLIENT_QUERY_STATUS="$(http_call GET "${ADMIN_REALMS_URL}/${REALM_NAME}/clients?clientId=${CLIENT_ID}")"
if [[ "$CLIENT_QUERY_STATUS" != "200" ]]; then
  echo "ERROR: Failed to query clients. HTTP ${CLIENT_QUERY_STATUS}"
  cat "$TMP_BODY"
  exit 1
fi

CLIENT_INTERNAL_ID="$(cat "$TMP_BODY" | json_extract "(data[0].get('id') if data else '')")"
if [[ -z "$CLIENT_INTERNAL_ID" ]]; then
  CREATE_CLIENT_PAYLOAD="$(cat <<JSON
{
  "clientId": "${CLIENT_ID}",
  "enabled": true,
  "protocol": "openid-connect",
  "publicClient": false,
  "standardFlowEnabled": true,
  "directAccessGrantsEnabled": false,
  "serviceAccountsEnabled": false,
  "redirectUris": ["${APP_CALLBACK_URL}"],
  "webOrigins": ["${APP_WEB_ORIGIN}"],
  "attributes": {
    "post.logout.redirect.uris": "${APP_POST_LOGOUT_REDIRECT_URI}"
  }
}
JSON
)"
  CREATE_CLIENT_STATUS="$(http_call POST "${ADMIN_REALMS_URL}/${REALM_NAME}/clients" "$CREATE_CLIENT_PAYLOAD")"
  if [[ "$CREATE_CLIENT_STATUS" != "201" ]]; then
    echo "ERROR: Failed to create client. HTTP ${CREATE_CLIENT_STATUS}"
    cat "$TMP_BODY"
    exit 1
  fi
  echo "  - Client created"

  CLIENT_QUERY_STATUS="$(http_call GET "${ADMIN_REALMS_URL}/${REALM_NAME}/clients?clientId=${CLIENT_ID}")"
  if [[ "$CLIENT_QUERY_STATUS" != "200" ]]; then
    echo "ERROR: Failed to query client after create. HTTP ${CLIENT_QUERY_STATUS}"
    cat "$TMP_BODY"
    exit 1
  fi
  CLIENT_INTERNAL_ID="$(cat "$TMP_BODY" | json_extract "(data[0].get('id') if data else '')")"
else
  echo "  - Client already exists"
fi

if [[ -z "$CLIENT_INTERNAL_ID" ]]; then
  echo "ERROR: Could not resolve client internal id."
  exit 1
fi

echo "[4/6] Fetch client secret"
CLIENT_SECRET_STATUS="$(http_call GET "${ADMIN_REALMS_URL}/${REALM_NAME}/clients/${CLIENT_INTERNAL_ID}/client-secret")"
if [[ "$CLIENT_SECRET_STATUS" != "200" ]]; then
  echo "ERROR: Failed to fetch client secret. HTTP ${CLIENT_SECRET_STATUS}"
  cat "$TMP_BODY"
  exit 1
fi
CLIENT_SECRET_VALUE="$(cat "$TMP_BODY" | json_extract "data.get('value','')")"

echo "[5/6] Ensure user exists: ${USERNAME}"
USER_QUERY_STATUS="$(http_call GET "${ADMIN_REALMS_URL}/${REALM_NAME}/users?username=${USERNAME}&exact=true")"
if [[ "$USER_QUERY_STATUS" != "200" ]]; then
  echo "ERROR: Failed to query users. HTTP ${USER_QUERY_STATUS}"
  cat "$TMP_BODY"
  exit 1
fi
USER_ID="$(cat "$TMP_BODY" | json_extract "(data[0].get('id') if data else '')")"

if [[ -z "$USER_ID" ]]; then
  CREATE_USER_PAYLOAD="$(cat <<JSON
{
  "username": "${USERNAME}",
  "enabled": true,
  "emailVerified": false
}
JSON
)"
  CREATE_USER_STATUS="$(http_call POST "${ADMIN_REALMS_URL}/${REALM_NAME}/users" "$CREATE_USER_PAYLOAD")"
  if [[ "$CREATE_USER_STATUS" != "201" ]]; then
    echo "ERROR: Failed to create user. HTTP ${CREATE_USER_STATUS}"
    cat "$TMP_BODY"
    exit 1
  fi
  echo "  - User created"

  USER_QUERY_STATUS="$(http_call GET "${ADMIN_REALMS_URL}/${REALM_NAME}/users?username=${USERNAME}&exact=true")"
  if [[ "$USER_QUERY_STATUS" != "200" ]]; then
    echo "ERROR: Failed to query user after create. HTTP ${USER_QUERY_STATUS}"
    cat "$TMP_BODY"
    exit 1
  fi
  USER_ID="$(cat "$TMP_BODY" | json_extract "(data[0].get('id') if data else '')")"
else
  echo "  - User already exists"
fi

if [[ -z "$USER_ID" ]]; then
  echo "ERROR: Could not resolve user id."
  exit 1
fi

echo "[6/6] Set user password"
RESET_PASSWORD_PAYLOAD="$(cat <<JSON
{
  "type": "password",
  "temporary": false,
  "value": "${USER_PASSWORD}"
}
JSON
)"
RESET_PASSWORD_STATUS="$(http_call PUT "${ADMIN_REALMS_URL}/${REALM_NAME}/users/${USER_ID}/reset-password" "$RESET_PASSWORD_PAYLOAD")"
if [[ "$RESET_PASSWORD_STATUS" != "204" ]]; then
  echo "ERROR: Failed to set user password. HTTP ${RESET_PASSWORD_STATUS}"
  cat "$TMP_BODY"
  exit 1
fi

echo
echo "Done."
echo "Realm:        ${REALM_NAME}"
echo "Client ID:    ${CLIENT_ID}"
echo "Username:     ${USERNAME}"
echo "Client Secret:${CLIENT_SECRET_VALUE}"
echo
echo "Set this to your .env if needed:"
echo "KEYCLOAK_CLIENT_ID=${CLIENT_ID}"
echo "KEYCLOAK_CLIENT_SECRET=${CLIENT_SECRET_VALUE}"
