import { defineConfig, devices } from '@playwright/test';
// テスト対象のURL
// Vite proxy が cookieDomainRewrite: 'localhost' を設定しているため、
// Cookie が一致するようホスト名も localhost を使う (127.0.0.1 では送信されない)。
const BASEURL = 'http://localhost:4173';
// 認証状態の保存先 (playwright-test/auth.setup.ts が出力する)
const AUTH_STATE = './playwright-test/.auth/default.json';

/**
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
    // テストファイルのディレクトリ
    testDir: './playwright-test',
    // テストファイルの拡張子
    testMatch: /.*\.test\.(js|jsx|ts|tsx)/,
    /* ファイル内のテストを並行して実行 */
    // fullyParallel: true,
    /* ソースコードに誤ってtest.onlyを残した場合、CIでビルドを失敗させる。 */
    //forbidOnly: !!process.env.CI,
    /* CIでのみリトライ */
    // retries: process.env.CI ? 2 : 0,
    /* CIでの並行テストを無効にする。 */
    // workers: process.env.CI ? 1 : undefined,
    workers: process.env.CI ? 1 : undefined,
    /* 使用するレポーター https://playwright.dev/docs/test-reporters を参照 */
    reporter: process.env.CI ? 'github' : [
        ['list'],
        ['html', { open: 'never' }], // ローカルでHTMLレポートを生成
        // ['html', { port: 9323 }],
        // ['json', { outputFile: 'test-results.json' }],
        // ['junit', { outputFile: 'test-results.xml' }],
    ],
    /* 下記のすべてのプロジェクトで共有する設定。 */
    use: {
        headless: true,
        baseURL: BASEURL,
        /* 失敗したテストをリトライする際にトレースを収集。*/
        trace: 'on-first-retry',
        video: 'on', //https://playwright.dev/docs/videos
    },
    projects: [
        // 開発用ログインで認証状態を作る。他の project はこれに依存する。
        { name: 'setup', testMatch: /.*\.setup\.ts/ },
        {
            name: 'Chrome Desktop',
            use: {
                ...devices['Desktop Chrome'],
                channel: 'chromium',
                isMobile: false,
                // setup が保存した認証済みセッションから開始する
                storageState: AUTH_STATE,
                launchOptions: {
                    args: ['--disable-web-security'],
                },
            },
            dependencies: ['setup'],
        },
        {
            name: 'Chrome Mobile',
            use: {
                ...devices['Pixel 5'],
                channel: 'chromium',
                isMobile: true,
                storageState: AUTH_STATE,
                launchOptions: {
                    args: ['--disable-web-security'],
                },
            },
            dependencies: ['setup'],
        },/*
        {
            name: 'Safari',
            use: {
                ...devices['Desktop Safari'],
                channel: 'webkit',
            },
        },
        {
            name: 'Mobile Safari',
            use: { 
            ...devices['iPhone 12'],
            channel: 'webkit',
            },
        },*/
    ],
    /* テストを開始する前にローカルの開発サーバーを実行 */
    webServer: {
        command: 'npm run preview',
        url: BASEURL,
        // reuseExistingServer: !process.env.CI,
    },
});


/**
 * 環境変数をファイルから読み込む。
 * https://github.com/motdotla/dotenv
 */
// require('dotenv').config();