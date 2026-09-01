# fastapi_app の作業ルール

Python のコーディング規約は以下に従う。
@../docs/coding-standards/python.md

- 命名・スタイルは ruff（`E` / `W` / `F` / `N` / `I`）により強制される。設定は `pyproject.toml` の `[tool.ruff.lint]`。
- 検証コマンドと実行範囲の判断は `run-checks` スキルに従う。完了報告の前に `uv run ruff check src test` を通すこと。
- DB スキーマの変更手順は `db-migration` スキルに従う。
- 既存コードには規約導入前の違反が残っている。**新規・変更するコードから規約に従う**こと。
  無関係な箇所の一括リネームは、依頼されていない限り行わない。
