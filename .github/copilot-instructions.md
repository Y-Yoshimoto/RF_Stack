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

## エージェント設定ファイルの同期ルール

- 共有するエージェント設定ファイルの正は `.github` 配下とする。
- 例外として `CLAUDE.md` は Claude 固有設定のため `.claude/CLAUDE.md` を正とし、`.github` には設置しない。
- `CLAUDE.md` を除き `.claude` 側を直接編集せず、`.github` 側のみ編集する。
- 編集後は以下を実行して同期する。

```bash
./scripts/sync-agent-customizations.sh sync
```

- 同期対象は `.github/skills`, `.github/agents`, `.github/instructions` の3ディレクトリ。
- 同期漏れの確認は以下を実行する。差分があれば exit 1 となる。

```bash
./scripts/sync-agent-customizations.sh --check
```

- 既定では同期先ファイルは `444` (read-only) になる。ディレクトリは `755` のまま維持される。
- コピーベースの同期のため、`.github` 側で削除・リネームしたファイルは `.claude` 側に残る。不要になったファイルは手動で削除する。
