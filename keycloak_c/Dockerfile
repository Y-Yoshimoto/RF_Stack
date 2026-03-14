# https://quay.io/repository/keycloak/keycloak?tab=info
# 設定/証明書ビルド用イメージ
# [起動最適化]
# (https://www.keycloak.org/server/configuration#_optimize_the_keycloak_startup)
FROM quay.io/keycloak/keycloak:latest AS builder
LABEL maintainer="y-yoshimoto"

# ヘルスチェック有効化
ENV KC_HEALTH_ENABLED=true
# メトリクス有効化
ENV KC_METRICS_ENABLED=true
# データベースの種類設定
# ENV KC_DB=postgres

# 検証用サーバー証明書の生成
WORKDIR /opt/keycloak
RUN keytool -genkeypair \
    -storepass password \
    -storetype PKCS12 \
    -keyalg RSA \
    -keysize 2048 \
    -dname "CN=server" \
    -alias server \
    -ext "SAN:c=DNS:localhost,IP:127.0.0.1" \
    -keystore conf/server.keystore
# 設定情報を元にしたKeycloakのビルド
RUN /opt/keycloak/bin/kc.sh build

# 最終イメージ
FROM quay.io/keycloak/keycloak:latest
# ビルド済みのKeyCloakを最終イメージにコピー
COPY --from=builder /opt/keycloak/ /opt/keycloak/

# 起動時にインポートするレルム情報をインポート
# COPY --chown=1000:0 realm.json /opt/keycloak/data/import/realm.json

VOLUME [ "/opt/keycloak/data" ]

# ks.shをエンドポイントに指定
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
