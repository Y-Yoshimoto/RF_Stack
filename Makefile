# 起動/ビルド用のMakefile

## Devコンテナ用
d-build:
	@docker compose build

d-up:
	@docker compose up -d
	docker compose ps

d-upb:
	@docker compose up -d --build
	docker compose ps

d-ps:
	@docker compose ps

d-down:
	@docker compose down

d-down-all:
	@docker compose down --rmi all --volumes --remove-orphans

d-clean:
	@docker compose down --rmi all --volumes --remove-orphans 
	@rm -rf ./react_app/node_modules
	@rm -f ./react_app/.npm_install.lock
	./react_app/auxiliary/clean-temporary-files.sh ./
	@rm -rf ./fastapi_app/.venv
	@rm -f ./fastapi_app/uv.lock
	./fastapi_app/auxiliary/clean-temporary-files.sh ./

## Productionコンテナ用
p-build:
	@docker compose -f docker-compose-prod.yaml build

p-up:
	@docker compose -f docker-compose-prod.yaml up -d

p-upb:
	@docker compose -f docker-compose-prod.yaml up -d --build

p-ps:
	@docker compose -f docker-compose-prod.yaml ps

p-down:
	@docker compose -f docker-compose-prod.yaml down

p-down-all:
	@docker compose -f docker-compose-prod.yaml down --rmi all --volumes --remove-orphans

p-clean:
	@docker compose -f docker-compose-prod.yaml down --rmi all --volumes --remove-orphans 
	@rm -rf ./react_app/node_modules
	@rm -f ./.npm_install.lock
	./react_app/auxiliary/clean-temporary-files.sh ./

p-logs:
	@docker compose -f docker-compose-prod.yaml logs -f

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