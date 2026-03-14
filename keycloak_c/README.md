# Keycloak

## 概要

Keycloakのカスタムイメージを作成するためのDockerfile設定及びデータ永続化領域

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
