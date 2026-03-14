import react from '@vitejs/plugin-react';
import { defineConfig } from "vitest/config";

// テストの実行環境のタイムゾーン指定
process.env.TZ = "Asia/Tokyo";
// テストの実行環境の言語を指定
process.env.LANG = "ja_JP.UTF-8";
import * as path from "path";
import { fileURLToPath } from 'node:url';
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin';
import { playwright } from '@vitest/browser-playwright';
const dirname = typeof __dirname !== 'undefined' ? __dirname : path.dirname(fileURLToPath(import.meta.url));

// More info at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon
export default defineConfig({
  plugins: [react()],
  test: {
    // reporters: ['json', 'default'],
    reporters: ['default'],
    globals: true,
    environment: "jsdom",
    printConsoleTrace: true,
    include: ["./src/**/*.{test,spec}.{js,ts,jsx,tsx}", "'./src/**/*.{test,spec}.?(c|m)[jt]s?(x)'"],
    exclude: ["node_modules", "dist", "build"],
    alias: {
      "@": path.resolve(__dirname, "./src")
    },
    // https://vitest.dev/guide/coverage.html#coverage
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,ts,jsx,tsx}'],
      exclude: [
        // テストコードは除外
        'src/**/*.{test,spec}.{js,ts,jsx,tsx}',
        // アプリケーション全体に関わるコンポーネントは除外
        'src/main.tsx', 'src/App.tsx', 'src/theme.tsx', 'src/serviceworker.js',
        // ルーティングに関わるファイルは除外
        'src/routes/**/*.{js,ts,jsx,tsx}'],
      reporter: ['text', 'json', 'html', 'lcov']
      // reporter: ['html'],
    },
    // https://vitest.dev/guide/browser/
    // https://vitest.dev/guide/browser/config.html
    browser: {
      provider: playwright(),
      enabled: true,
      headless: true,
      viewport: {
        width: 1280,
        height: 720
      },
      // default { width: 414, height: 896 }
      screenshotFailures: false,
      instances: [{
        browser: 'chromium'
      }]
    },
    // projects: [{
    //   extends: true,
    //   plugins: [
    //     // The plugin will run tests for the stories defined in your Storybook config
    //     // See options at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon#storybooktest
    //     storybookTest({
    //       configDir: path.join(dirname, '.storybook')
    //     })],
    //   test: {
    //     name: 'storybook',
    //     browser: {
    //       enabled: true,
    //       headless: true,
    //       provider: playwright({}),
    //       instances: [{
    //         browser: 'chromium'
    //       }]
    //     },
    //     setupFiles: ['.storybook/vitest.setup.ts']
    //   }
    // }]
  }
});