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
- `npm run playwright` は `playwright.config.ts` の `webServer` 設定により **`npm run preview`（本番ビルド）を先に走らせる**ため時間がかかる。lint やユニットテストで足りる変更では実行しない。
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
- コンテナ起動時に entrypoint が `uv sync` と `.venv` の有効化を済ませているが、コマンドは `uv run` を付けて実行する方が確実。

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

## 5. 結果の報告

- **失敗した場合は出力をそのまま示す。** 「テストが通った」と要約する前に、実際の exit code と出力を確認する。
- 検証を実行しなかった場合は「実行していない」と明示する。実行したかのように書かない。
- 既存の失敗（自分の変更と無関係な失敗）を見つけた場合は、その旨を切り分けて報告する。
