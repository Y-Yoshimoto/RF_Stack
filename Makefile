# 起動/ビルド用のMakefile
COMPOSE := docker compose -f ./docker-compose.yaml
PROD_COMPOSE := docker compose -f ./docker-compose-prod.yaml

## Devコンテナ用
d-build:
	@$(COMPOSE) build

# Devコンテナ操作
d-up:
	@$(COMPOSE) up -d
	$(COMPOSE) ps

d-upb:
	@$(COMPOSE) up -d --build
	$(COMPOSE) ps

# Devコンテナの状態確認
d-ps:
	@$(COMPOSE) ps

# 対話シェル
d-exec:
	@$(COMPOSE) exec $(SERVICE) bash

# 任意コマンドを非対話で実行
#   例: make d-run SERVICE=react_app CMD="npm run lint" 
d-run:
	@$(COMPOSE) exec -T $(SERVICE) $(CMD)

# Devコンテナ停止
d-down:
	@$(COMPOSE) down

# 全コンテナ停止・削除（イメージ・ボリューム・孤立コンテナも含む）
d-down-all:
	@$(COMPOSE) down --rmi all --volumes --remove-orphans

# コンテナ/一時ファイルのクリーンアップ
d-clean:
	@$(COMPOSE) down --rmi all --volumes --remove-orphans 
	@rm -rf ./react_app/node_modules
	@rm -f ./react_app/.npm_install.lock
	./react_app/auxiliary/clean-temporary-files.sh ./
	@rm -rf ./fastapi_app/.venv
	@rm -f ./fastapi_app/uv.lock
	./fastapi_app/auxiliary/clean-temporary-files.sh ./
### PostgreSQLコンテナの再生作成
d-reset-db:
	@$(COMPOSE) down --volumes postgres_c 
	@$(COMPOSE) up -d --build postgres_c

## Productionコンテナ用
p-build:
	@$(PROD_COMPOSE) build

p-up:
	@$(PROD_COMPOSE) up -d

p-upb:
	@$(PROD_COMPOSE) up -d --build

p-ps:
	@$(PROD_COMPOSE) ps

p-down:
	@$(PROD_COMPOSE) down

p-down-all:
	@$(PROD_COMPOSE) down --rmi all --volumes --remove-orphans

p-clean:
	@$(PROD_COMPOSE) down --rmi all --volumes --remove-orphans 
	@rm -rf ./react_app/node_modules
	@rm -f ./.npm_install.lock
	./react_app/auxiliary/clean-temporary-files.sh ./

p-logs:
	@$(PROD_COMPOSE) logs -f

## 両方のコンテナ用
e-build: d-build p-build
e-up: d-up p-up
e-upb: d-upb p-upb
e-down: d-down p-down
e-down-all: d-down-all p-down-all
e-clean: d-clean p-clean
	
## Kubernetes用
k-runtime:
	kubectl version 
	kubectl get nodes
	kubectl get pods -o wide -n kube-system

k-pods:
	kubectl get pods -o wide -n react-app-prod

k-deploy:
	kubectl apply -f prod-manifest.yaml

k-status:
	kubectl get deployments -n react-app-prod
	kubectl get services -n react-app-prod

k-delete:
	kubectl delete -f prod-manifest.yaml

k-logs:
	kubectl logs -f deploy/react-app-prod-nginx-deployment -n react-app-prod