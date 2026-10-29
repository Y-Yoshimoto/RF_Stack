---
name: run-checks
description: このリポジトリで lint・テスト・カバレッジ・型/複雑度チェックを実行するための手順とコマンド集。React(react_app / npm・ESLint・Vitest・Playwright)と FastAPI(fastapi_app / uv・ruff・pytest)の両方を対象とし、コンテナ内外の判定方法を含む。「lintして」「テストを流して」「検証して」「カバレッジを見て」といった依頼や、コードを変更したあとの動作確認時に使用する。
---

# 検証コマンド実行手順

## 1. 実行環境を判定する

コマンドの叩き方が環境によって変わる。**必ず最初に判定する。**

```bash
test -f /.dockerenv
```

| 結果 | 環境 | 実行方法 |
| --- | --- | --- |
| 成功 (exit 0) | コンテナ内 | コマンドをそのまま実行する |
| 失敗 (exit 1) | ホスト | `make d-run` 経由でコンテナ内に流し込む |

### ホストから実行する場合

```bash
make d-run SERVICE=react_app CMD="npm run lint"
```

実体は `docker compose exec -T <SERVICE> <CMD>`。以下に注意する。

- **対象コンテナが起動している必要がある。** `exec` は停止中のコンテナには使えない。`make d-ps` で確認し、落ちていれば `make d-up` で起動する。
- サービス名は `react_app` / `fastapi_app` / `postgres_c` / `keycloak_c`。
- 各コンテナの作業ディレクトリは `/work/<サービス名>` に設定済みなので、`cd` は不要。
- `docker compose` と `make` は**ホスト側でしか使えない**。コンテナ内から呼ばない。

---

## 2. React (`react_app`)

| 目的 | コマンド |
| --- | --- |
| Lint | `npm run lint` |
| Lint(自動修正) | `npm run lint:fix` |
| Lint(HTMLレポート) | `npm run lint:report` |
| 循環的複雑度チェック | `npm run lint:complexity` |
| **ユニットテスト** | **`npx vitest run`** |
| ユニットテスト(対象を絞る) | `npx vitest run src/sample/pages/ButtonPage` |
| カバレッジ | `npm run coverage` |
| E2E テスト | `npm run playwright` |
| E2E レポート表示 | `npm run playwright:report` |
| ビルド確認 | `npm run build` |
| 依存関係グラフ | `npm run madge` |

### 注意点

- **`npm run test` を使わない。** 中身は `vitest`（ウォッチモード）で、非対話環境では終了せずハングする。単発実行は必ず `npx vitest run`。同様に `npm run test:ui` / `npm run storybook` / `npm run playwright:ui` も常駐するので検証には使わない。
- `npm run lint` は `--max-warnings 0` 付き。**警告が1件でもあれば失敗する。**
- `npm run lint` には命名規約(`@typescript-eslint/naming-convention`)の検査が含まれ、`src/` 配下は `error` で判定される。
  型情報を使うため通常の lint より時間とメモリを要する(スクリプト側で `NODE_OPTIONS=--max-old-space-size=3072` を付与済み)。
  規約の内容は `docs/coding-standards/react-typescript.md` を参照。
- Vitest はブラウザモード（chromium, headless）が有効。ブラウザの実体は `PLAYWRIGHT_BROWSERS_PATH` が指す `node_modules/playwright/.local-browsers` にある。ここが未インストールだとテストが起動しない。
- テスト対象は `src/**/*.{test,spec}.{js,ts,jsx,tsx}`（実装とコロケート）。
- `npm run playwright` は `playwright.config.ts` の `webServer` 設定により **`npm run preview`（ビルド）を先に走らせる**ため時間がかかる。lint やユニットテストで足りる変更では実行しない。
- Playwright は `setup` project が開発用ログインバイパスで認証状態を作り、`storageState` として各テストに引き継ぐ。
  そのため**実行には `fastapi_app` / `keycloak_c` / `redis_c` の起動が必要**（§5 参照）。認証に失敗した場合は setup が原因を示すエラーを出す。
- ビルドのモードで開発用機能の有無が変わる。`npm run dev` / `build` / `preview` は `mode=development`（バイパス有効）、
  `npm run build:production` は `mode=production`（無効）。
- カバレッジ対象からは `src/main.tsx` / `App.tsx` / `theme.tsx` / `serviceworker.js` / `src/routes/**` が除外されている。

---

## 3. FastAPI (`fastapi_app`)

| 目的 | コマンド |
| --- | --- |
| Lint | `uv run ruff check src` |
| Lint(自動修正) | `uv run ruff check --fix src` |
| フォーマット | `uv run ruff format src` |
| テスト | `uv run pytest` |
| テスト(ファイル指定) | `uv run pytest test/test_00_runtime.py` |
| テスト(コロケート分) | `uv run pytest src/rest_sample/` |
| カバレッジ | `uv run pytest --cov=src --cov-report=term` |
| 循環的複雑度チェック | `uv run lizard src` |
| マイグレーション状態 | `uv run alembic -c alembic/alembic_control_plane.ini current` |

### 注意点

- パッケージ管理は **uv**。`pip` を直接使わない。依存追加は `uv add`。
- ruff は `E` / `W` / `F` / `N`(pep8-naming) / `I`(isort) を有効化している。規約の内容は `docs/coding-standards/python.md` を参照。`I` の違反は `--fix` で自動修正できる。
- `pytest.ini` の `testpaths = test` により、**引数なしの `uv run pytest` は `test/` ディレクトリしか実行しない。** `src/` 配下にコロケートされたテスト（`test_ut_*.py` / `test_it_*.py`）を動かすにはパスを明示する。
- `pytest.ini` の `addopts` により、実行のたびに `pytest_report.html` が生成・上書きされる。これは成果物なのでコミットしない。
- `test/` 配下は `test_00_` / `test_99_` のように**数値プレフィックスで実行順を制御**している。新規追加時はこの規約に従う。
- DB に接続するテストは開発用 PostgreSQL に触れる。**データを壊す可能性がある操作を含むテストは、事前に影響を確認する。**
- コンテナ起動時に entrypoint が `uv sync` と仮想環境(`/usr/local/uv`)の有効化を済ませているが、コマンドは `uv run` を付けて実行する方が確実。

---

## 4. どこまで実行するかの判断

すべてを毎回流す必要はない。変更内容に応じて範囲を決める。

| 変更内容 | 実行する検証 |
| --- | --- |
| 単純なリファクタ・軽微な修正 | lint |
| ロジック・関数の変更 | lint → 該当箇所のユニットテスト |
| コンポーネント/エンドポイントの追加・変更 | lint → ユニットテスト（全体） |
| 画面遷移・ユーザー導線の変更、`data-testid` の変更 | 上記 + E2E |
| 見た目・レイアウトの変更 | 上記 + ブラウザでの目視確認（dev server は `http://localhost:5173/`） |
| DB スキーマの変更 | 上記 + マイグレーションの適用確認 |

## 5. 認証後の画面を確認する（開発用ログインバイパス）

認証が必要な画面は、KeyCloak のログイン画面を経由せずに確認できる。次の URL を開くだけで、
あらかじめ用意された認証情報でログインした状態になる。

```
http://localhost:5173/dev-login
```

| クエリ | 内容 |
| --- | --- |
| `as` | 使用するプロファイル名。既定は `alpha-admin`。`cp-admin` / `cp-viewer` / `alpha-admin` / `alpha-member` / `beta-member`（02 §7.2） |
| `next` | ログイン後の遷移先パス(同一オリジンのパスのみ)。既定は AP のプロファイルが `/{tenant_code}/`(例: `alpha-admin` は `/alpha/`)、CP のプロファイルが `/cp/`。例: `/dev-login?as=cp-viewer&next=/cp/tenants` |

FastAPI に直接アクセスして Cookie だけ得ることもできる。

```bash
curl -i "http://localhost:8000/api/auth/dev-login?as=alpha-admin"
```

前提:

- `docker compose up -d` で `fastapi_app` / `keycloak_c` / `redis_c` が起動していること
- `APP_ENV=development` かつ `AUTH_DEV_LOGIN_ENABLED=true` であること
  （どちらかを満たさない場合、エンドポイントは登録されず **404** になる）
- KeyCloak の Realm / クライアント / ユーザーが作成済みであること
  （未作成ならシードを実行する。シードは開発用テナント `alpha` / `beta` と `control-plane` を払い出しと同じ関数で作る。`tenant-provisioning` スキル参照）

プロファイルと開発用の認証情報は `fastapi_app/src/modules/auth/dev_profiles.py` に 1 箇所で定義し、シードと共有する（`DEV_PROFILES` / `DEV_TENANTS` / `DEV_TENANT_USERS`、要素は `DevUser`）。開発用パスワードは `APP_ENV=development` 以外では読めない。
AP のプロファイルは Cookie `rf_sid_app`、CP のプロファイルは `rf_sid_cp` のセッションを作る（状態確認は `/api/auth/app/status` / `/api/auth/cp/status`）。
権限の異なるユーザーを追加する場合は `dev_profiles.py` にユーザーを足し、シードを再実行する。

> **この機能は開発専用。** 認証済みセッションを無条件に発行するため、`APP_ENV` が
> `development` 以外のときは有効化できず、有効化を要求すると起動時にエラーになる。
> フロントエンドの `/dev-login` も `npm run build:production` ではバンドルから除去される。

### Keycloak のログイン画面を実際に通る E2E

上記のバイパス（`auth.setup.ts` が使う dev-login）を使わず、Keycloak のログインフォーム（`keycloak_c` の実画面）を通る E2E は別プロジェクト（`Keycloak Desktop` / `Keycloak Mobile`）に分けている。テストは `react_app/playwright-test/keycloak/` にある。

```bash
make d-run SERVICE=react_app CMD="npm run playwright:keycloak"                                   # 両プロジェクト
make d-run SERVICE=react_app CMD="npm run playwright:keycloak -- --project='Keycloak Desktop'"   # 片方だけ
make d-run SERVICE=react_app CMD="npm run playwright:keycloak -- app_login"                      # ファイル指定 (app_login / cp_login)
```

- `npm run playwright` には含まれない（`E2E_KEYCLOAK=1` のときだけ project を切り替える。このとき既存の `setup` / `Chrome *` と `npm run preview` は使わない）。
- ブラウザは preview（4173）ではなく **Vite の dev サーバー（5173）** を使う。BFF のコールバック先とログイン後の遷移先が `APP_CALLBACK_URL` / `FRONTEND_URL`（5173）だからである。起動済みならそれを使い、無ければ Playwright が `npm run dev` を起動する。
- 前提: `fastapi_app` / `keycloak_c` / `redis_c` / `postgres_c` が起動し、シード（§5 の前提）が投入済みであること。Keycloak のユーザーは参照のみで、テストは作成・変更しない。
- `react_app` コンテナ内の `localhost:8080`（BFF が返す `KEYCLOAK_EXTERNAL_URL`）は、サイドカー `keycloak_forward`（socat）が `keycloak_c:8080` へ転送するため、Chromium の名前解決は書き換えない（`--host-resolver-rules` の既定は空）。サイドカーが無い環境でだけ `E2E_KEYCLOAK_HOST_RULES='MAP localhost:8080 keycloak_c:8080'` を指定する。`E2E_KEYCLOAK_BASEURL` で対象 URL を変更できる。
- Keycloak プロジェクトのワーカーは 1 に固定している（`setup` が無く、複数ワーカーが同時に `test-results` を作ると bind mount 上で `ENOTDIR` になることがあるため）。
- 開発用パスワードは `fastapi_app/src/modules/auth/dev_profiles.py` の `_DEV_PASSWORD` を `playwright-test/keycloak/dev_credentials.ts` が読む（リポジトリ全体が `/work` にマウントされているため）。読めない環境では環境変数 `E2E_DEV_PASSWORD` を指定する。ユーザー名もこのファイルの 1 箇所に置く。
- Keycloak の画面のロケーターは `playwright-test/keycloak/pages/keycloak_login_page.ts` だけにあり、Keycloak 更新で壊れた場合はここを直す。
- 誤ったパスワードのテストは専用ユーザー（`alpha-member2`）を使う。Keycloak のブルートフォース検知（`bruteForceProtected`）のカウントが他のテストのユーザーへ波及しないようにするため。連続して実行しすぎると一時ロックされうるが、ロック中も「エラーが表示される」ことは変わらない。

### 新しい画面の E2E（`playwright-test/screens/`）

CP のテナント管理、AP のユーザー・組織・ToDo の画面を、開発用ログイン（`alpha-admin` / `alpha-member` / `beta-member` / `cp-admin` / `cp-viewer`）で通す E2E。`npm run playwright` に含まれ、`Screens Desktop` / `Screens Mobile` プロジェクトで実行される。

```bash
make d-run SERVICE=react_app CMD="npm run playwright"                                  # 既存 + 画面の E2E（setup が全プロファイルの認証状態を作る）
make d-run SERVICE=react_app CMD="npm run playwright -- screens"                       # 画面の E2E だけ
make d-run SERVICE=react_app CMD="npm run playwright -- screens/app_todos"             # ファイル指定（cp_tenants / app_organizations / app_users / app_todos）
```

- 対象は Vite の **dev サーバー（5173）**（`playwright.config.ts` が起動済みならそれを使い、無ければ起動する）。変更系の API は `Origin` が `FRONTEND_URL`（5173）か `CSRF_TRUSTED_ORIGINS` のものでないと 403 になるため、`vite preview`（4173）では動かない。preview で動かす場合は FastAPI の `CSRF_TRUSTED_ORIGINS` に `http://localhost:4173` を足し、`E2E_SCREEN_BASEURL` で指定する。
- 複数の利用者が登場するシナリオは、`playwright-test/fixtures.ts` の `openAs(profile)` で利用者ごとのブラウザコンテキストを開く。前提データの用意と失敗時の後片付けは `playwright-test/helpers/api.ts`（API。`Origin` と `X-Requested-With` を付ける）。
- **テストはデータを作り、実行後に自動で削除される（ティアダウン）。** 組織・ToDo は画面で削除し、CP のテナントは「削除を要求」まで、ユーザーは「無効にする」までを画面で検証する。これらの使い捨てデータ（CP のテナント `e2e-<8 文字>`、alpha のユーザー `e2e-<8 文字>@example.com`、ToDo `E2E ToDo <8 文字>`、組織 `E2E Org <8 文字>`）は、`setup` プロジェクトの `teardown` に指定した `cleanup` プロジェクト（`playwright-test/cleanup.teardown.ts`）が、全プロジェクトの完了後に 1 回だけ開発専用 API `POST /api/dev/e2e-cleanup`（FastAPI `dev_tools/e2e_cleanup.py`。命名は完全一致で判定し、シードのデータは常に除外）を呼んで物理削除する。テストが途中で失敗して残ったデータも同じ実行で消える。
  - 認証は `cp-admin`（`.auth/cp-admin.json`）、Origin / `X-Requested-With` を付けて dev サーバー経由で呼ぶ。同期処理でテナント数に比例して時間がかかる（タイムアウト 4 分）。409（別の後片付けが実行中）は 5 秒待って 1 回だけ再試行する。
  - **後片付けの失敗ではテストを赤にしない。** 失敗（HTTP エラー・通信失敗・`ok=false`）は `[teardown] 警告:` を出して終わる。結果は `[teardown] 後片付け: テナント削除 N / ... ok=true` の 1 行で出力される。開発専用機能が無効だと 404 になり、警告だけが出てデータは残る。
  - 残骸の確認（件数のみ）: `docker compose exec -T fastapi_app uv run python -m dev_tools.e2e_cleanup --dry-run`。消す場合は `--dry-run` を外す（次回の E2E 実行でも消える）。
  - ティアダウンは `npm run playwright`（`setup` に依存するプロジェクトを実行したとき）だけ。`npm run playwright:keycloak` は `setup` に依存せずデータを作らない（Keycloak のユーザーは参照のみ）ため呼ばない。
  - サンプル画面・サンプル API に依存する E2E（`sample_ButtonPueh` / `sample_FetchPage` / `sample_PageTitle`）は、サンプルをアプリから外したため `playwright.config.ts` の `SAMPLE_TESTS`（`testIgnore`）で実行対象外にしている。
- **後片付け（手動）:** テストが残した `e2e-*` のテナント・ユーザー・組織・ToDo は `make d-run SERVICE=fastapi_app CMD="uv run python -m dev_tools.e2e_cleanup --dry-run"`（`--dry-run` を外すと削除）で消せる。同じ処理を `POST /api/dev/e2e-cleanup?dry_run=`（CP の `saas_admin` + CSRF ヘッダー。開発用ログイン有効時のみ）でも呼べる。
- 前提: §5 の前提に加え、`keycloak_c` が Keycloak の管理 API を呼べること（テナント・ユーザーの作成が実際にレルム・ユーザーを作る）。

## 6. 結果の報告

- **失敗した場合は出力をそのまま示す。** 「テストが通った」と要約する前に、実際の exit code と出力を確認する。
- 検証を実行しなかった場合は「実行していない」と明示する。実行したかのように書かない。
- 既存の失敗（自分の変更と無関係な失敗）を見つけた場合は、その旨を切り分けて報告する。
