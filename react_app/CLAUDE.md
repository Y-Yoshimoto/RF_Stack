# react_app の作業ルール

React / TypeScript のコーディング規約は以下に従う。
@../docs/coding-standards/react-typescript.md

- 命名規約は ESLint（`@typescript-eslint/naming-convention`）により `error` で強制される。
  ルール本体は `auxiliary/naming_rules.js`。例外を追加する場合はこのファイルと規約ドキュメントの両方を更新する。
- 検証コマンドと実行範囲の判断は `run-checks` スキルに従う。完了報告の前に `npm run lint` を通すこと。
- 既存コードには規約導入前の違反が残っている。**新規・変更するコードから規約に従う**こと。
  無関係な箇所の一括リネームは、依頼されていない限り行わない。
