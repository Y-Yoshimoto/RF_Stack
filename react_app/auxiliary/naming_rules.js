/**
 * @typescript-eslint/naming-convention のルール定義（単一ソース）
 *
 * 規約の本文: docs/coding-standards/react-typescript.md
 *
 * 中核となる考え方:
 *   - データ（値を保持するもの）は snake_case … PEP8 に寄せる
 *   - 関数（呼び出すもの）は camelCase   … JavaScript の慣習に従う
 *   - React コンポーネントは PascalCase、カスタムフックは use + camelCase
 *     → これは慣習ではなく動作要件。eslint-plugin-react-hooks が
 *        /^use[A-Z0-9]/ と /^[A-Z]/ で判別しているため、破ると検査対象から外れる。
 *
 * 注意:
 *   - types: ['function'] はデータと関数の判別に型情報を使う。
 *     eslint.config.js 側で parserOptions.projectService を有効にしておくこと。
 *   - naming-convention は「最も具体的にマッチしたセレクタ」を適用し、
 *     具体度が同じ場合は配列の後方が優先される。順序を入れ替える際は注意すること。
 *
 * 例外を追加する場合は、このファイルの EXCEPTIONS 節に filter 付きルールとして追記し、
 * あわせて docs/coding-standards/react-typescript.md の §5 も更新すること。
 */

/** 既定・型・定数に関するルール */
const BASE_RULES = [
    // 既定はデータとみなして snake_case
    { selector: 'default', format: ['snake_case'], leadingUnderscore: 'allow', trailingUnderscore: 'allow' },

    // import 名は供給側（外部ライブラリ）依存のため検査しない
    { selector: 'import', format: null },

    // 型・クラス・interface・enum は PascalCase（PEP8 の CapWords と一致）
    { selector: 'typeLike', format: ['PascalCase'] },
    { selector: 'enumMember', format: ['UPPER_CASE'] },

    // モジュールレベル定数は UPPER_SNAKE_CASE も許容
    { selector: 'variable', modifiers: ['const', 'global'], format: ['snake_case', 'UPPER_CASE'] },
];

/**
 * 関数に関するルール（データとの分離）
 *
 * naming-convention は「より具体的なセレクタ」を優先する。BASE_RULES の
 * { variable, modifiers: ['const','global'] } はモジュールレベルの関数代入にもマッチしてしまうため、
 * 関数側には modifiers と types の両方を持たせて必ず上回るようにしている。
 * （ルールを増減した際は fixture で実挙動を再確認すること）
 */
const FUNCTION_RULES = [
    // 関数（const への代入を含む）は camelCase
    { selector: 'function', format: ['camelCase'] },
    { selector: 'variable', types: ['function'], format: ['camelCase'] },
    // モジュールレベルの const 関数（BASE_RULES の定数ルールより具体的にする）
    { selector: 'variable', modifiers: ['const', 'global'], types: ['function'], format: ['camelCase'] },

    // React コンポーネント: 関数だが PascalCase（JSX で DOM 要素と区別されるため必須）
    { selector: 'function', filter: { regex: '^[A-Z]', match: true }, format: ['PascalCase'] },
    { selector: 'variable', types: ['function'], filter: { regex: '^[A-Z]', match: true }, format: ['PascalCase'] },
    { selector: 'variable', modifiers: ['const', 'global'], types: ['function'], filter: { regex: '^[A-Z]', match: true }, format: ['PascalCase'] },
];

/** メンバー（型プロパティ・クラスメンバ）に関するルール */
const MEMBER_RULES = [
    // 型プロパティ・props: データは snake_case、関数値は camelCase（onClick 等）
    { selector: 'typeProperty', format: ['snake_case'] },
    { selector: 'typeProperty', types: ['function'], format: ['camelCase'] },

    // クラスプロパティ: データは snake_case、関数値は camelCase
    { selector: 'classProperty', format: ['snake_case'] },
    { selector: 'classProperty', types: ['function'], format: ['camelCase'] },
    { selector: 'classProperty', modifiers: ['private'], format: ['snake_case'], leadingUnderscore: 'require' },

    // クラスメソッドは camelCase。private は _ を必須とする
    { selector: 'classMethod', format: ['camelCase'] },
    { selector: 'classMethod', modifiers: ['private'], format: ['camelCase'], leadingUnderscore: 'require' },
];

/** 例外規定（docs/coding-standards/react-typescript.md §5 と対応） */
const EXCEPTIONS = [
    // オブジェクトリテラルのプロパティ: MUI の sx 等、外部ライブラリ境界が機械判別できない。
    // 自前データの形は typeProperty 側の検査で担保する。
    { selector: 'objectLiteralProperty', format: null },

    // 分割代入の shorthand: 供給側の名前をそのまま受けるため検査しない。
    // ※ リネームを伴う分割代入（const { camera_id: cameraId } = res）は検査対象に残る。
    { selector: 'variable', modifiers: ['destructured'], format: null },

    // 未使用マーカー（eslint.config.js の no-unused-vars varsIgnorePattern と整合）
    { selector: ['variable', 'parameter'], filter: { regex: '^_mock', match: true }, format: null },

    // createContext の戻り値は JSX で <Xxx.Provider> として使うため PascalCase
    { selector: 'variable', filter: { regex: 'Context$', match: true }, format: ['PascalCase'] },

    // Vite の環境変数命名規約（src/vite-env.d.ts）
    { selector: 'typeProperty', filter: { regex: '^VITE_', match: true }, format: null },
];

/** src/ 配下に適用する命名規則 */
export const NAMING_RULES = [...BASE_RULES, ...FUNCTION_RULES, ...MEMBER_RULES, ...EXCEPTIONS];

/**
 * Storybook の CSF に適用する命名規則
 * named export（export const Primary: Story）は Storybook の規約により PascalCase を許容する。
 */
export const STORYBOOK_RULES = [...NAMING_RULES, { selector: 'variable', modifiers: ['exported', 'const'], format: ['PascalCase', 'snake_case', 'UPPER_CASE'] }];
