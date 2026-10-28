---
name: dev-environment
description: Dev Container 開発環境の初期セットアップ、起動・停止、依存関係の再インストール、環境が壊れたときの復旧手順。docker compose / Makefile / .env の扱いとポート一覧を含む。「環境を立ち上げて」「コンテナが起動しない」「npm install が終わらない」「権限エラーが出る」「環境を作り直したい」といった依頼で使用する。
---

# 開発環境の構築・復旧手順

**`docker compose` と `make` はホスト側でしか実行できない。** コンテナ内（`test -f /.dockerenv` が成功する環境）からは実行しない。

## サービスとポート

| サービス | 用途 | ホスト公開ポート |
| --- | --- | --- |
| `react_app` | React 開発サーバ | 5173(dev server)、4173(vite preview)、6006(Storybook)、9323(Playwright レポート) |
| `fastapi_app` | FastAPI | 8000 |
| `postgres_c` | PostgreSQL | 5432 |
| `keycloak_c` | Keycloak | 8080、8443、9000 |

`npm run storybook`(6006) と `npm run preview`(4173) はいずれもホストのブラウザから開ける。どちらも常駐プロセスなので、確認が終わったら停止すること。

---

## 1. 初期セットアップ

### 1-1. `.env` を作成する

`.env.default` をコピーし、**自分の UID/GID を設定する**。これを誤るとマウントしたファイルの所有権が壊れる。

```bash
cd react_app && ./auxiliary/generate-env-file.sh && cd ..
```

このスクリプトは `.env.default` をリポジトリルートの `.env` にコピーし、末尾に `USER_ID=$(id -u)` と `GROUP_ID=$(id -g)` を追記する（後勝ちで既定値を上書きする）。`react_app/` 内から実行する必要がある（`../.env` を相対参照しているため）。既存の `.env` は上書きされない。上書きしたい場合は `--force`。

> ルートの `README.md` には `./generateEnvfile.sh` と書かれているが、**その名前のファイルはリポジトリに存在しない**。上記が正しい手順。

**`.env` の中身は読み取らない。** スキーマ確認が必要な場合は `.env.default` を参照する。

### 1-2. ビルドと起動

```bash
make d-build
make d-up
make d-ps
```

### 1-3. 依存インストールの完了を待つ

コンテナ起動時に entrypoint が依存をインストールする。**この間はコマンドを実行しても失敗する。**

| コンテナ | 実行内容 | 進行中を示すロックファイル |
| --- | --- | --- |
| `react_app` | `npm install --include=dev --force` と Playwright ブラウザ(chromium / chromium-headless-shell / webkit)のインストール | `react_app/.npm_install.lock` |
| `fastapi_app` | `uv sync --locked`（失敗時は `uv sync`）と仮想環境の有効化(`$UV_PROJECT_ENVIRONMENT` = `/usr/local/uv`。バインドマウント上の `.venv` ではなくコンテナ内固有の場所に置くことで、依存インストール時のファイルコピー競合を回避している。この場所は名前付きボリュームで、作り直しても残る。後述) | `fastapi_app/.uv_install.lock` |

**ロックファイルが存在する間はインストール中。消えるまで待つ。** 特に react_app はブラウザのダウンロードを伴うため初回は時間がかかる。

```bash
ls react_app/.npm_install.lock fastapi_app/.uv_install.lock 2>/dev/null || echo "インストール完了"
```

> `README.md` には `.npm.lock` と書かれているが、実際のファイル名は `.npm_install.lock`。

**fastapi_app は 2 回の `uv sync` がどちらも失敗するとコンテナが非 0 で終了する**（原因を示すメッセージを出し、`.uv_install.lock` は削除される）。`docker compose logs fastapi_app` で uv の出力を確認する。以前は失敗しても CMD に進み、`uvicorn` が見つからず exit 127 になっていた。

### 1-4. fastapi_app の仮想環境ボリューム

`fastapi_app` の Python 依存は、コンテナを作り直しても再ダウンロードしないよう、次の名前付きボリュームに置いている（`docker-compose.yaml` の `volumes`）。実体名はプロジェクト名が前置される（例: `rf_stack_fastapi_uv_venv`。`docker volume ls | grep fastapi_uv` で確認）。

| ボリューム | マウント先 | 内容 |
| --- | --- | --- |
| `fastapi_uv_venv` | `/usr/local/uv` | uv の仮想環境（`UV_PROJECT_ENVIRONMENT`） |
| `fastapi_uv_cache` | `/usr/local/uv-cache` | uv のキャッシュ（`UV_CACHE_DIR`） |

- 空のボリュームは初回にイメージの内容と所有者（`vscode`、`USER_ID` / `GROUP_ID`）で初期化される。**初回起動だけ全パッケージをダウンロードする**（85 パッケージ・約 140MB。回線次第で数分）。2 回目以降の `uv sync` は差分なしで数秒で終わる。
- `make d-down` / `docker compose up -d` による作り直しではボリュームは残る。**`make d-down-all` / `make d-clean`（`--volumes`）は削除する。**
- ボリュームはイメージを再ビルドしても**再初期化されない**（空のときだけイメージの内容で初期化される）。`Dockerfile_dev` の Python バージョンを上げた、`USER_ID` / `GROUP_ID` を変えた、仮想環境が壊れた場合は、ボリュームを削除して入れ直す。
- ダウンロード耐性のため `Dockerfile_dev` で `UV_HTTP_TIMEOUT=300` / `UV_CONCURRENT_DOWNLOADS=4` を設定している。

**依存を入れ直したいとき**（`fastapi_app` だけを対象にする。DB など他のボリュームは消えない）:

```bash
make d-down                                       # コンテナを停止・削除（ボリュームは残る）。他の担当が使用中でないか確認してから
docker volume ls | grep fastapi_uv                # 実体名を確認
docker volume rm <プロジェクト名>_fastapi_uv_venv    # 仮想環境を削除
docker volume rm <プロジェクト名>_fastapi_uv_cache   # キャッシュも消す場合のみ（通常は残してよい）
make d-up                                         # 起動。entrypoint が最初から uv sync する
```

`make d-down` は全サービスを止めるため、`fastapi_app` だけを止める場合は `docker compose rm -sf fastapi_app` を使ってもよい。ボリュームを使用中のコンテナがあると `docker volume rm` は失敗する。

---

## 2. 日常の操作

```bash
make d-up          # 起動
make d-ps          # 状態確認
make d-down        # 停止（イメージ・ボリュームは残す）
make d-upb         # ビルドし直して起動
make d-exec SERVICE=react_app                      # 対話シェル
make d-run SERVICE=react_app CMD="npm run lint"    # 単発コマンド
```

各コンテナの作業ディレクトリは `/work/<サービス名>`。リポジトリ全体が `/work/` にマウントされている。

---

## 3. 復旧手順

**軽いものから順に試す。いきなり全削除しない。**

### レベル1: 再起動

```bash
make d-down
make d-up
```

### レベル2: イメージを作り直す

Dockerfile や `docker-compose.yaml` を変更した場合。

```bash
make d-upb
```

### レベル3: 依存関係を作り直す

`node_modules` が壊れた、依存を更新したのに反映されない場合。**`make d-clean` はイメージとボリュームも削除する**ため、影響を理解した上で実行する。

```bash
make d-clean   # ★確認を取ってから
make d-upb
```

`d-clean` が消すもの: コンテナ・イメージ・ボリューム・孤立コンテナ、`react_app/node_modules`、`react_app/.npm_install.lock`、および各アプリの一時ファイル（`dist` / `coverage` / `test-results` / `playwright-report` / `eslint-report.html` 等）。

`fastapi_app` の依存だけを入れ直す場合は、`d-clean` ではなく「1-4. fastapi_app の仮想環境ボリューム」の手順で `fastapi_uv_venv` だけを削除する。

### レベル4: DB を初期化する

```bash
make d-reset-db   # ★★ 全データが失われる。必ず確認を取る
```

---

## 4. よくある失敗

| 症状 | 原因と対処 |
| --- | --- |
| `make d-run` が「service not running」等で失敗する | コンテナが停止している。`make d-ps` で確認し `make d-up` |
| ファイルの所有権が `root` になる / 書き込めない | `.env` の `USER_ID` / `GROUP_ID` がホストと不一致。`id -u` / `id -g` の値と照合し、直したら `make d-upb` |
| `npm install` が終わらない・コマンドが見つからない | entrypoint のインストールが進行中。`.npm_install.lock` が消えるまで待つ |
| Vitest / Playwright がブラウザ起動に失敗する | Playwright ブラウザが未インストール。`make d-run SERVICE=react_app CMD="npx playwright install chromium"` |
| `fastapi_app` が起動直後に終了する / `uv sync` のタイムアウト | `docker compose logs fastapi_app` で原因を確認。ネットワーク由来なら再度 `make d-up`（取得済みの分はキャッシュに残るので続きから進む）。仮想環境の破損ならボリュームを削除（1-4） |
| FastAPI で `ModuleNotFoundError` | `PYTHONPATH=/work/fastapi_app/src/` に依存している。compose の environment を確認する |
| DB に接続できない | `postgres_c` の起動と、`DB_HOST=postgres_c` / `DB_PORT=5432` および `CP_DB_*` / `APP_DB_*` 環境変数を確認。`role ... does not exist` なら旧構成の initdb のままなので `make d-reset-db`（要確認） |
| ポートが衝突する | 4173 / 5173 / 6006 / 8000 / 8080 / 8443 / 9000 / 9323 / 5432 のいずれかをホスト側で他プロセスが使用している |
| Dev Container の設定変更が反映されない | VS Code の再ビルド（Rebuild Container）が必要 |

---

## 5. 破壊的なターゲット

以下は**実行前に必ず影響を説明し、承認を得る**。

| コマンド | 影響 |
| --- | --- |
| `make d-down-all` / `make p-down-all` | イメージ・ボリューム（`fastapi_uv_venv` / `fastapi_uv_cache` を含む）・孤立コンテナを削除 |
| `make d-clean` / `make p-clean` | 上記に加え `node_modules` と一時ファイルを削除 |
| `make d-reset-db` | **PostgreSQL のボリュームを削除。全データが失われる** |
| `make k-delete` | Kubernetes のリソースを削除 |
