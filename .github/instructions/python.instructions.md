---
applyTo: "fastapi_app/**"
---

Python のコーディング規約は `docs/coding-standards/python.md` に従う。

- PEP8 準拠。行長は 240、import 順序は ruff の isort に従う。
- 命名・スタイルは ruff（`E` / `W` / `F` / `N` / `I`）により強制される。設定は `fastapi_app/pyproject.toml`。
