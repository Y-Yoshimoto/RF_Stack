---
applyTo: "react_app/**"
---

React / TypeScript のコーディング規約は `docs/coding-standards/react-typescript.md` に従う。

- データは `snake_case`、関数は `camelCase`。
- React コンポーネントは `PascalCase`、カスタムフックは `use` + `camelCase`（動作要件のため PEP8 より優先する）。
- 命名規約は ESLint により `error` で強制される。ルール本体は `react_app/auxiliary/naming_rules.js`。
