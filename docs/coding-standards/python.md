# Python コーディング規約

## 1. 目的

`fastapi_app` の Python コードは **PEP8 準拠**とする。本ドキュメントでは PEP8 の内容を再掲せず、**本リポジトリでの決定事項と例外**を定める。

TypeScript 側も PEP8 に寄せた命名規約を採用している（[React / TypeScript コーディング規約](./react-typescript.md)）。両者を行き来する際の差分は最小限になるよう設計している。

## 2. 命名規則（PEP8）

| 対象 | 形式 | 例 |
| --- | --- | --- |
| モジュール・パッケージ | `lowercase_with_underscores` | `db_connector`, `sql_models.py` |
| クラス | `CapWords` | `DBConnector`, `HttpClient` |
| 関数・メソッド・変数・引数 | `snake_case` | `create_db_engine`, `get_session` |
| 定数 | `UPPER_SNAKE_CASE` | `DB_HOST`, `DEFAULT_TIMEOUT` |
| 非公開 | `_` 接頭辞 | `_internal_state`, `_build_payload` |
| 型変数 | `CapWords` | `T`, `ModelT` |

## 3. 本リポジトリでの決定事項

- **行長は 240**（`ruff` の `line-length`）。PEP8 の 79 は採用しない。
- **import 順序**は `ruff` の isort（`I`）に従う。`ruff check --fix` で自動整形できる。
- **型ヒントを必ず付ける。** Python 3.14 のため `from __future__ import annotations` は不要。組み込みジェネリクス（`list[str]`）と `X | None` を使う。
- **docstring は日本語**で書く（既存踏襲）。FastAPI のルータ関数の docstring は OpenAPI の description に反映されるため、特に丁寧に書く。
- `pydocstyle`（`D`）は**有効化しない**。docstring の形式は強制せず、内容の質で担保する。
- 設定値は `os.environ` から読む。**`.env` ファイルは読み取らない**（スキーマ確認が必要な場合のみ `.env.default` を参照）。

## 4. ruff による強制

```toml
[tool.ruff]
line-length = 240

[tool.ruff.lint]
select = ["E", "W", "F", "N", "I"]
ignore = [
    "E402", # Module level import not at top of file
]
```

| ルール | 内容 |
| --- | --- |
| `E` / `W` | pycodestyle（PEP8 のスタイル全般） |
| `F` | pyflakes（未使用 import、未定義名など） |
| `N` | pep8-naming（§2 の命名規則） |
| `I` | isort（import 順序） |

> `ruff` の既定の `select` は `["E4", "E7", "E9", "F"]` で、pycodestyle の大半と pep8-naming は**有効になっていない**。上記のとおり明示的に `select` する必要がある。

`E402`（モジュール先頭以外での import）は、サブアプリのルータ定義で意図的に使っているため除外している。

実行方法は `run-checks` スキルに従う。ホストからは以下。

```bash
make d-run SERVICE=fastapi_app CMD="uv run ruff check src test"
make d-run SERVICE=fastapi_app CMD="uv run ruff check --fix src test"
```

## 5. 例外規定

現時点で恒久的な例外は定めていない。やむを得ず逸脱する場合は、行単位で `# noqa: <ルールID>` に理由コメントを添える。

```python
from control_plane_app.models.sql_models import *  # noqa: F403 # モデルをすべて読み込む必要があるため
```

例外を恒久化する場合は `pyproject.toml` の `[tool.ruff.lint]` に追記し、**本ドキュメントの本節も更新すること**。

## 6. パッケージ管理

- パッケージ管理は **uv**（`pyproject.toml` / `uv.lock`）。`pip` を直接使わない。
- 依存追加は `uv add`、開発用依存は `uv add --dev`。
- コマンド実行は `uv run <command>`。

## 7. 移行状況

本規約の導入時点では、既存コードに以下の違反が残っている。**設定とドキュメントの整備が先行しており、既存コードの修正は別作業**として進める。

| 箇所 | ルール | 内容 |
| --- | --- | --- |
| `src/control_plane_app/models/sql_models.py` | N801 | `T_Tenant` |
| `test/HttpClient/Client.py` | N801 | `Client_ABC` |
| `test/HttpClient/Client.py` | N802 | `addQuery_string` |
| `test/HttpClient/Client.py`, `ClientSimple.py` | N999 | モジュール名が `CapWords` |

`T_Tenant` はテーブル名 `t_tenant` との対応を示す意図で付けられているが、`__tablename__ = "t_tenant"` を明示指定しているため、**クラス名のリネームは DB スキーマとマイグレーションに影響しない**（参照箇所も 3 箇所のみ）。
