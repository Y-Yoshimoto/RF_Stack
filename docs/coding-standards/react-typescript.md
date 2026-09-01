# React / TypeScript コーディング規約

## 1. 目的

本リポジトリは `react_app`（React / TypeScript）と `fastapi_app`（Python）を**同じメンバーが編集する**。言語をまたぐたびに命名の流儀が変わるコストを下げるため、TypeScript 側も **PEP8 をベースにした命名規約**を採用する。

ただし React には文法・ライブラリ由来の制約があり、これを破ると動作しなくなる。**React の制約を最優先し、そのうえで PEP8 に寄せる**。

## 2. 基本原則

1. **React の制約が最優先** — コンポーネントは `PascalCase`、カスタムフックは `use` + `camelCase`。これは慣習ではなく動作要件（§3.1 参照）。
2. **データは `snake_case`、関数は `camelCase`** — これが本規約の中核。値を保持するものは Python と同じ書き方、呼び出すものは JavaScript の慣習に従う。
3. **外部との境界は検査しない** — 外部ライブラリ・バックエンド API が定める名前は、こちらで変えられない。無理に合わせず例外として扱う（§5）。

## 3. 命名規則

| 対象 | 形式 | 例 |
| --- | --- | --- |
| データ変数・パラメータ | `snake_case` | `camera_list`, `comp_width` |
| 関数（`const` への代入を含む） | `camelCase` | `formatDate`, `compareAppVersion` |
| React コンポーネント | `PascalCase` | `OperationSlider` |
| カスタムフック | `use` + `camelCase` | `useComponentSize` |
| モジュールレベル定数 | `UPPER_SNAKE_CASE` | `DB_NAME`, `INTERVAL_UPDATE_TOKEN` |
| 型（`type` / `interface` / `enum`） | `PascalCase` | `CameraDetailProps` |
| `enum` メンバー | `UPPER_SNAKE_CASE` | `CompareResult.EQUAL` |
| 型プロパティ・props（データ） | `snake_case` | `camera_id`, `tenant_name` |
| 型プロパティ・props（関数値） | `camelCase` | `onClick`, `onChangeValue` |
| クラスプロパティ（データ） | `snake_case` | `camera_id`, `_internal_state` |
| クラスメソッド・関数プロパティ | `camelCase` | `fetchDetail`, `_buildPayload` |

クラスメンバの可視性は接頭辞で表す。`public` は接頭辞なし、`private` は `_` を**必須**、`protected` は `_` を付けてもよい。

```ts
// データは snake_case、関数は camelCase
const camera_list: Camera[] = [];
const formatDate = (value: Date): string => { /* ... */ };

// コンポーネントは PascalCase、フックは use + camelCase
export function OperationSlider() { /* ... */ }
const useComponentSize = () => { /* ... */ };

// 型プロパティはデータと関数値で分ける
type CameraDetailProps = {
  camera_id: string;      // データ → snake_case
  tenant_name: string;
  onClick: () => void;    // 関数値 → camelCase
};
```

### 3.1 コンポーネントとフックの命名が動作要件である理由

`eslint-plugin-react-hooks` は、**識別子の名前だけ**でフックとコンポーネントを判別している。

```js
// node_modules/eslint-plugin-react-hooks/cjs/eslint-plugin-react-hooks.development.js
function isHookName(s)      { return /^use[A-Z0-9]/.test(s); }
function isComponentName(node) { return /^[A-Z]/.test(node.name); }
```

つまり `use_fetch_data` は**フックとして認識されない**。`rules-of-hooks`（条件分岐内でのフック呼び出しの検出など）の検査対象から静かに外れ、バグを見逃す。同様に小文字始まりの関数は JSX で DOM 要素として解釈される。

**この 2 つは PEP8 より優先する。**

## 4. ファイル命名規則

新規ファイルから適用する。既存ファイルは移行作業の中で `git mv` により随時リネームする。

| 対象 | 形式 | 例 |
| --- | --- | --- |
| コンポーネント | `PascalCase.tsx`（またはディレクトリ + `index.tsx`） | `OperationSlider/index.tsx` |
| カスタムフック | `useXxx.ts` / `useXxx.tsx` | `useComponentSize.ts` |
| その他のモジュール | `snake_case.ts` | `comparison_app_version.ts` |
| ユニットテスト | 対象ファイル名 + `.spec.ts(x)` | `index.spec.tsx` |

## 5. 例外規定

以下は ESLint 設定（§6）で許容済みの正当な例外である。

| 例外 | 理由 |
| --- | --- |
| `_mock` で始まる変数・パラメータ | 未使用マーカー。既存の `no-unused-vars` の `varsIgnorePattern` と整合させる |
| オブジェクト分割代入の shorthand<br>`const { pathname } = useLocation()` | 供給側（外部ライブラリ・API レスポンス）の名前をそのまま受けるため検査対象外 |
| `Context` サフィックスの const（`AuthContext` 等） | `createContext` の戻り値は JSX で `<Xxx.Provider>` として使うため `PascalCase` とする |
| `VITE_*` の型プロパティ（`src/vite-env.d.ts`） | Vite の環境変数命名規約 |
| クォート必須のプロパティ（`'Content-Type'` 等） | HTTP ヘッダー等の外部仕様 |
| オブジェクトリテラルのプロパティ | MUI の `sx` 等、外部ライブラリ境界が機械判別できないため検査対象外。自前データの形は型プロパティ側の検査で担保する |
| `import` 名 | 供給側（外部ライブラリ）依存のため検査対象外 |
| Storybook の CSF named export（`export const Primary: Story`） | Storybook の規約により `PascalCase` を許容 |

### 分割代入で「受けるだけ」と「リネーム」は区別する

shorthand は検査対象外だが、**リネームを伴う分割代入は検査対象**になる。バックエンドが `snake_case` を返すのだから、そのまま受けること。

```ts
const { camera_id } = res;                 // OK: shorthand（検査対象外）
const { camera_id: cameraId } = res;       // NG: camelCase へのリネームは違反
```

### バックエンド API のフィールド名

FastAPI 側は SQLModel のフィールドがそのまま JSON になるため、基本的に `snake_case` で返る（`external_id`, `created_at` 等）。本規約とは自然に一致する。

例外的な casing のフィールド（`isOffline`, `coordinate_X` 等）が外部仕様として存在する場合、フロントから変更できないため ESLint 設定の `filter` で個別に許容する。API 契約の型は `src/utils/libs/FetchComponents/type.ts` を起点に定義する。

### それ以外の逸脱

やむを得ず規則から外れる場合（外部ライブラリへ props を透過する箇所等）は、行単位で理由コメントを添えて許容する。

```ts
// eslint-disable-next-line @typescript-eslint/naming-convention -- MUI の API 名をそのまま透過するため
const { maxWidth } = props;
```

MUI 等の外部ライブラリへ props をスプレッドする境界では、**分割代入 shorthand（検査対象外）で受けて渡す**ことを推奨する。

## 6. ESLint による強制

`@typescript-eslint/naming-convention` により本規約を機械的にチェックする。

- ルール本体は **`react_app/auxiliary/naming_rules.js`** に `NAMING_RULES` / `STORYBOOK_RULES` として定義し、`eslint.config.js` から import する（単一ソース）。
- `src/` 配下に **`error`** として適用する。`npm run lint` は `--max-warnings 0` のため、違反があれば失敗する。
- データと関数の判別に**型情報**を使うため、対象は tsconfig にカバーされる `src/**/*.{ts,tsx,js,jsx}` のみ。`.storybook/` と `playwright-test/` は対象外（広げると型情報エラーになる）。
- 型情報チェックはメモリを多く使うため、`lint` / `lint:fix` / `lint:report` には `NODE_OPTIONS=--max-old-space-size=3072` を付与している。
- `src/**/*.stories.{ts,tsx,js,jsx}` には `STORYBOOK_RULES`（named export の `PascalCase` を許容）を適用する。

実行方法は `run-checks` スキルに従う。ホストからは以下。

```bash
make d-run SERVICE=react_app CMD="npm run lint"
```

> **例外を追加するとき**: §5 の例外は `naming_rules.js` 内の `filter` 付き allow ルールとして表現している。新たな例外を追加する場合は**このファイルに追記し、本ドキュメントの §5 も更新すること**。

## 7. その他

- 行長は 240（Prettier の `printWidth`）。整形は Prettier に任せ、ESLint は `eslint-config-prettier` で整形系ルールを無効化している。
- 循環的複雑度は 15 以下、1 ファイル 500 行以下（既存の ESLint 設定）。
- `any` を使わない。`unknown` + 絞り込み、またはジェネリクスで表現する。

## 8. 移行状況

本規約の導入時点では、既存コードに違反が残っている。**設定とドキュメントの整備が先行しており、既存コードの修正は別作業**として進める。新規・変更するコードから本規約に従うこと。
