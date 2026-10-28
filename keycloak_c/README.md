# Keycloak

## 概要

Keycloakのカスタムイメージを作成するためのDockerfile設定及びデータ永続化領域

## Realm / Client / User の作成

テナント用の Realm・Client・User は、`fastapi_app` コンテナ内の CLI で冪等に作成する。
クライアントシークレットは `KC_CLIENT_SECRET_SEED` から導出した値を CLI が設定し、FastAPI も同じ値を導出する (`.env` への転記は不要)。
詳細 (環境変数・シークレットの扱い) は [KEYCLOAK_SETUP.md](./KEYCLOAK_SETUP.md) の「2. 自動化 CLI で作成する方法」を参照。

```bash
make d-run SERVICE=fastapi_app CMD="uv run python -m modules.keycloak_admin.cli tenant-a fastapi-app user001"
```

実装は `fastapi_app/src/modules/keycloak_admin/` にあり、コントロールプレーンからのテナント払い出しでも同じ部品を使う。

## 永続化データのクリア

```bash
rm -rf ./keycloak_c/data/h2
rm -rf ./keycloak_c/data/transaction-logs
```

## データベースの接続

[データベースの接続](https://www.keycloak.org/server/db)

## リバースプロキシの設定

[リバースプロキシの設定](https://www.keycloak.org/server/reverseproxy)
[コンテキストルートの設定](https://www.keycloak.org/server/hostname#_using_a_reverse_proxy)

## 参考ドキュメント

- [Keycloak](https://www.keycloak.org/)
- [Docker導入](https://www.keycloak.org/getting-started/getting-started-docker#_taking_the_next_step)
- [コンテナ運用](https://www.keycloak.org/server/containers)
