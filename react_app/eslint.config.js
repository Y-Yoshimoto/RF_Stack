// For more info, see https://github.com/storybookjs/eslint-plugin-storybook#configuration-flat-config-format
import storybook from "eslint-plugin-storybook";

import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import eslintConfigPrettier from "eslint-config-prettier";
// 命名規約のルール本体(単一ソース)。規約: docs/coding-standards/react-typescript.md
import { NAMING_RULES, STORYBOOK_RULES } from './auxiliary/naming_rules.js'


export default tseslint.config({ ignores: ['dist', 'playwright-report'] }, {
  extends: [js.configs.recommended, ...tseslint.configs.recommended, eslintConfigPrettier],
  files: ['**/*.{ts,tsx,js,jsx}'],
  languageOptions: {
    ecmaVersion: 2020,
    globals: globals.browser,
  },
  plugins: {
    'react-hooks': reactHooks,
    'react-refresh': reactRefresh,
  },
  rules: {
    // React Hooks用の推奨ルールを適用
    ...reactHooks.configs.recommended.rules,
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    // 環境変数使用の警告をオフ
    'no-process-env': ['off'],
    // 'react-refresh/only-export-components'の警告をオフ
    'react-refresh/only-export-components': 'off',
    // _や__で始まる変数名、_mockで始まる変数名を無視
    '@typescript-eslint/no-unused-vars': ['warn', { 'varsIgnorePattern': '^(_|__.*|_mock.*)$' }],
    // 循環的複雑度の警告
    // "complexity": ["warn", 0],
    "complexity": ["warn", 15],
    // ファイルの最大行数を500に設定
    "max-lines": ["warn", 500],
    // React Hooksの依存関係配列の警告をオフ
    "react-hooks/exhaustive-deps": ['off'],
  },
},
// 命名規約(docs/coding-standards/react-typescript.md)
// データは snake_case / 関数は camelCase の判別に型情報を使うため、
// tsconfig にカバーされる src/ 配下のみを対象とする。
// .storybook/ と playwright-test/ は tsconfig の対象外のため含めない(含めると型情報エラーになる)。
{
  files: ['src/**/*.{ts,tsx,js,jsx}'],
  languageOptions: {
    parserOptions: {
      projectService: true,
      tsconfigRootDir: import.meta.dirname,
    },
  },
  rules: {
    '@typescript-eslint/naming-convention': ['error', ...NAMING_RULES],
  },
},
// Storybook の CSF は named export の PascalCase を許容する
{
  files: ['src/**/*.stories.{ts,tsx,js,jsx}'],
  rules: {
    '@typescript-eslint/naming-convention': ['error', ...STORYBOOK_RULES],
  },
}, storybook.configs["flat/recommended"]);
