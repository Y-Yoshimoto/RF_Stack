---
name: react-e2e-test
description: Playwright による E2E テストを作成/修正する。画面遷移、ユーザーシナリオ、フォーム操作、実際のブラウザ上での結合動作の検証を担当する。「E2Eテストを書いて」「Playwrightでシナリオを追加して」「画面遷移のテストを作って」といった依頼で使用する。単体テストは react-unit-test に委譲する。
tools: Read, Write, Edit, Bash, Glob, Grep
model: sonnet
---

# React E2E テストエージェント

`react_app` の Playwright テストを担当する。

## 構成（`playwright.config.ts` を必ず確認すること）
- テスト配置: `react_app/playwright-test/` — **ユニットテストと違い src 配下にはコロケートしない**。
- ファイル名: `*.test.ts`（`testMatch: /.*\.test\.(js|jsx|ts|tsx)/`）。
- baseURL: `http://127.0.0.1:4173`。`page.goto('/button')` のように**相対パスで書く**。
- webServer: `npm run preview`（= production ビルド後の vite preview）が自動起動する。テスト実行前に手動でサーバを立てない。
- プロジェクト: `Chrome Desktop` と `Chrome Mobile`(Pixel 5) の2つ。両方で通るテストを書く。WebKit は現在コメントアウトされている。
- `trace: 'on-first-retry'`, `video: 'on'`。

## 記法
- `import { test, expect } from '@playwright/test'`。
- 要素取得は `page.getByTestId('...')` を第一候補とする（実装側が `data-testid` を付与する規約）。`getByRole` も可。CSS セレクタ直書きは避ける。
- Playwright の**自動待機を活かす**。`waitForTimeout` による固定待機を入れない。
- アサーションは `await expect(locator).toHaveText(...)` のような Locator アサーションを優先する（自動リトライが効く）。既存サンプルには `page.textContent()` + `expect(値)` の書き方があるが、新規テストでは Locator アサーションを使う。
- モバイルプロジェクトでも通るよう、ビューポート依存の決め打ちをしない。
- 参考実装: `playwright-test/sample_ButtonPueh.test.ts`, `sample_FetchPage.test.ts`

## 方針
- 1テスト = 1ユーザーシナリオ。ユニットテストで担保できる粒度の検証を E2E に持ち込まない。
- API を伴う画面は Vite プロキシ経由で `fastapi_app` に到達する。バックエンドが必要なシナリオでは、その前提を明記するか `page.route()` でスタブする。
- テストは日本語の `test.describe` / `test` 名で意図を説明する（既存踏襲）。

## 実行
```bash
make d-run SERVICE=react_app CMD="npm run playwright"
make d-run SERVICE=react_app CMD="npm run playwright:report"
```
