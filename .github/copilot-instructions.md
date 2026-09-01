# Copilot Instructions

## 開発環境
- 開発環境はDev Containerを使用し、VS Code/Remote Containers機能で開発を行うことを推奨する。
- マルチコンテナの環境のため、docker compose up -d で開発コンテナを起動する。
- Makefile を使用して他の開発コンテナの操作を行うことができる。
- ホストマシンからは docker compose exec を使用して、コンテナ内のシェルにアタッチしたり、コマンドを実行したりできる。
- ホスト環境には各種実行環境はインストールしない。

### 実行環境の判定とコマンド実行方法
- test -f /.dockerenv が成功した場合はコンテナ内のため、コマンドをそのまま実行する。(例: `npm run lint`)
- test -f /.dockerenv が失敗した場合はホスト環境のため、docker compose exec を使用してコンテナ内でコマンドを実行する。(例: `docker compose exec react_app npm run lint`)
- make d-runを使用しても、ホスト環境からコンテナ内のコマンドを実行できる。(例: `make d-run SERVICE=react_app CMD="npm run lint"`)
- この判定は、コンテナ内の実行環境を必要とするすべてのコマンドで適用する。(npm, python, etc.)
- docker compose, make コマンドはホスト側でのみ使用できる。

## アプリケーション構成
以下はいずれも docker-compose.yaml のサービス名であり、docker compose exec / make d-run の SERVICE に指定する値と一致する。
- react_app: Reactフロントエンドアプリケーション
- fastapi_app: FastAPIバックエンドアプリケーション
- keycloak_c: Keycloak認証サーバー
- postgres_c: PostgreSQLデータベース

本番構成(docker-compose-prod.yaml)には以下のサービスが存在する。
- rproxy: リバースプロキシ
- rsync_dist: ビルド成果物の配布用

## Git
- デフォルトブランチはdevelopを設定する。指示がない場合developからブランチを作成し、プルリクエストもdevelopに対して行う。
- ファイルの移動は、git mv コマンドを使用する。
- git rebase -i コマンドを使用してコミット履歴を整理することも推奨する。
- コミットメッセージには以下のプレフィックスを使用する。
  + add: ファイルの追加
  + feat: 新機能の追加
  + fix: バグ修正
  + docs: ドキュメントの変更
  + style: コードのスタイル変更（機能に影響しない）
  + refactor: リファクタリング
  + test: テストの追加・修正
  + chore: その他の変更（ビルドプロセスや補助ツールの変更など）
- aiエージェントがコミットする場合は、コミットメッセージの先頭に `ai/(プレフィックス)` を付ける。(例: `ai/fix: 同期スクリプトの権限設定を修正`)

## GitHub
- プルリクエストのタイトル及び説明は日本語で記述する。
- 指示がない限りプルリクエストには、package-lock.jsonなどの依存関係ファイルの変更を含めないことを推奨する。

## envファイルの扱い
- .envファイルは、ファイル読取ツールに限らず、いかなる手段でも読取を行わないこと。
- .envファイルのスキーマ把握が必要な場合は、.env.default ファイルを参照すること。

## コーディング規約

- コーディング規約の正は `docs/coding-standards/` 配下とする。
  + `docs/coding-standards/python.md` — Python(PEP8 準拠)
  + `docs/coding-standards/react-typescript.md` — React / TypeScript(PEP8 ベース)
- **インストラクションファイルに規約本文を転記しない。** 参照のみとし、正は常に docs 側とする。
- TypeScript も PEP8 に寄せ、**データは `snake_case`、関数は `camelCase`** とする。
  ただし React コンポーネントの `PascalCase` とカスタムフックの `use` + `camelCase` は動作要件のため優先する。
- 規約は ESLint(`@typescript-eslint/naming-convention`)と ruff(`E`/`W`/`F`/`N`/`I`)により機械的に強制される。
- 行長は両言語とも 240。

### ディレクトリ単位での適用

アプリケーション(Dev コンテナ)単位で規約が自動的に効くよう、以下を配置している。ツールごとに機構が異なるため、両者は同期せずそれぞれ手で維持する(いずれも数行の参照のみ)。

| ツール | 機構 | 配置 |
| --- | --- | --- |
| Claude Code | サブディレクトリの `CLAUDE.md`(配下のファイルにアクセスした時点で読み込まれる) | `react_app/CLAUDE.md`, `fastapi_app/CLAUDE.md` |
| GitHub Copilot | `.github/instructions/*.instructions.md` の `applyTo` グロブ | `.github/instructions/` |

## エージェントの役割分担

タスクは以下の担当エージェントに委譲する。定義の実体は `.github/agents/` にある。

| エージェント | 担当範囲 |
| --- | --- |
| `react-ui` | React の画面・MUI コンポーネント・テーマ・Storybook |
| `react-domain` | React のフック・データ取得・型定義・ドメインモデル |
| `react-unit-test` | Vitest + Testing Library によるユニットテスト |
| `react-e2e-test` | Playwright による E2E テスト |
| `fastapi-api-schema` | FastAPI のエンドポイント・ルータ構成・リクエスト/レスポンススキーマ |
| `fastapi-domain` | FastAPI のビジネスロジック・共通モジュール |
| `postgres-schema` | SQLModel のテーブル定義・Alembic マイグレーション・DB設計 |
| `fastapi-pytest` | pytest によるユニット/結合テスト |
| `api-contract-sync` | React と FastAPI 間の API 契約の整合性検証 |
| `auth-keycloak` | Keycloak 認証・認可（React と FastAPI を横断） |
| `infra-docker` | docker-compose・Dockerfile・Makefile・nginx・k8s マニフェスト |

- UI とロジック、実装とテストは担当を分ける。1エージェントに複数レイヤーを担当させない。
- API のシグネチャを変更した場合は `api-contract-sync` で影響範囲を確認する。
- 認証・認可はレイヤーごとに分割せず、`auth-keycloak` が両サイドを一貫して担当する。
- コーディング規約はディレクトリ単位のインストラクションで自動的に反映されるため、エージェント定義には転記しない。

## スキル

手順として整理したものは `.github/skills/` にスキルとして置く。

| スキル | 内容 |
| --- | --- |
| `run-checks` | lint・テスト・カバレッジの実行方法（React / FastAPI、コンテナ内外の判定を含む） |
| `db-migration` | Alembic によるマイグレーションの生成・レビュー・適用・ロールバック |
| `dev-environment` | Dev Container の初期セットアップ、起動・停止、依存の再インストール、復旧手順 |

- 検証コマンドやマイグレーション手順を各エージェント定義に転記せず、スキル側を正とする。

## エージェント設定ファイルの同期ルール

- 共有するエージェント設定ファイルの正は `.github` 配下とする。
- 例外として `CLAUDE.md` は Claude 固有設定のため設置場所そのものを正とし、`.github` には置かない。
  リポジトリ全体は `.claude/CLAUDE.md`、アプリ単位は `react_app/CLAUDE.md` / `fastapi_app/CLAUDE.md`。
- `.github/instructions/` は GitHub Copilot 専用(`applyTo` フロントマター)であり、**同期対象に含めない**。
  Claude 側の対応機構はサブディレクトリの `CLAUDE.md`。
- `CLAUDE.md` を除き `.claude` 側を直接編集せず、`.github` 側のみ編集する。
- 編集後は以下を実行して同期する。

```bash
./scripts/sync-agent-customizations.sh sync
```

- 同期対象は `.github/skills`, `.github/agents` の2ディレクトリ。
- 同期漏れの確認は以下を実行する。差分があれば exit 1 となる。

```bash
./scripts/sync-agent-customizations.sh --check
```

- 既定では同期先ファイルは `444` (read-only) になる。ディレクトリは `755` のまま維持される。
- コピーベースの同期のため、既定では `.github` 側で削除・リネームしたファイルが `.claude` 側に残る。
  孤児ファイルを削除する場合は `--prune` を付ける(削除対象は標準出力に列挙される)。

```bash
./scripts/sync-agent-customizations.sh sync --prune
```
