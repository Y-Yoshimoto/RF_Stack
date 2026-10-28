import { defineConfig, devices } from '@playwright/test';
import { SCREEN_BASEURL } from './playwright-test/constants';
// テスト対象のURL
// Vite proxy が cookieDomainRewrite: 'localhost' を設定しているため、
// Cookie が一致するようホスト名も localhost を使う (127.0.0.1 では送信されない)。
const BASEURL = 'http://localhost:4173';
// 認証状態の保存先 (playwright-test/auth.setup.ts が出力する)
const AUTH_STATE = './playwright-test/.auth/default.json';

// Keycloak のログイン画面を実際に通る E2E (playwright-test/keycloak/)。
// `E2E_KEYCLOAK=1` のときだけ project と webServer を切り替える (npm run playwright:keycloak。run-checks スキル §5)。
// 通常の `npm run playwright` (開発用ログインで認証状態を作る既存のテスト) には含めず、このときは既存の project / preview も使わない。
const KEYCLOAK_TESTS = /keycloak[\\/].*\.test\.(js|jsx|ts|tsx)/;
const KEYCLOAK_E2E = process.env.E2E_KEYCLOAK === '1';
// 新しい画面の E2E (playwright-test/screens/)。データを作成・変更する (変更系の API は preview の Origin では CSRF で拒否される) ため、
// Vite の dev サーバー (SCREEN_BASEURL) を対象にする別プロジェクトで実行する。認証状態は setup が作る (Cookie はポートに依存しない)。
const SCREEN_TESTS = /screens[\\/].*\.test\.(js|jsx|ts|tsx)/;
// BFF は Keycloak からのコールバック先とログイン後の遷移先に APP_CALLBACK_URL / FRONTEND_URL (Vite の dev サーバー) を使うため、
// ブラウザは preview (4173) ではなく dev サーバーで操作する。
// ワーカー数。Keycloak のプロジェクトは setup を持たず、複数のワーカーが最初に同時に test-results を作ると、
// bind mount (Docker Desktop) 上で mkdir が ENOTDIR で失敗することがあるため 1 にする (通常のプロジェクトは setup が先に作るので影響しない)。
const WORKERS = process.env.CI || KEYCLOAK_E2E ? 1 : undefined;
const KEYCLOAK_BASEURL = process.env.E2E_KEYCLOAK_BASEURL ?? 'http://localhost:5173';
// BFF は Keycloak の URL を KEYCLOAK_EXTERNAL_URL (http://localhost:8080) で返す。react_app コンテナの中の localhost:8080 には
// サイドカー (docker-compose.yaml の keycloak_forward) が Keycloak へ転送するため、既定では Chromium の名前解決を書き換えない。
// サイドカーが無い環境で必要な場合だけ、E2E_KEYCLOAK_HOST_RULES で --host-resolver-rules の値を指定する
// (例: 'MAP localhost:8080 keycloak_c:8080')。
const KEYCLOAK_HOST_RULES = process.env.E2E_KEYCLOAK_HOST_RULES ?? '';
const KEYCLOAK_LAUNCH_ARGS = KEYCLOAK_HOST_RULES ? [`--host-resolver-rules=${KEYCLOAK_HOST_RULES}`] : [];

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
    workers: WORKERS,
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
    projects: KEYCLOAK_E2E ? [
        // Keycloak 経由のログイン (E2E_KEYCLOAK=1)。認証状態 (storageState) を持たず、setup にも依存しない (テスト自身がログインする)。
        {
            name: 'Keycloak Desktop',
            testMatch: KEYCLOAK_TESTS,
            use: {
                ...devices['Desktop Chrome'],
                channel: 'chromium',
                baseURL: KEYCLOAK_BASEURL,
                launchOptions: { args: KEYCLOAK_LAUNCH_ARGS },
            },
        },
        {
            name: 'Keycloak Mobile',
            testMatch: KEYCLOAK_TESTS,
            use: {
                ...devices['Pixel 5'],
                channel: 'chromium',
                baseURL: KEYCLOAK_BASEURL,
                launchOptions: { args: KEYCLOAK_LAUNCH_ARGS },
            },
        },
    ] : [
        // 開発用ログインで認証状態を作る。他の project はこれに依存する。
        { name: 'setup', testMatch: /.*\.setup\.ts/ },
        {
            name: 'Chrome Desktop',
            testIgnore: [KEYCLOAK_TESTS, SCREEN_TESTS],
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
            testIgnore: [KEYCLOAK_TESTS, SCREEN_TESTS],
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
        },
        {
            name: 'Screens Desktop',
            testMatch: SCREEN_TESTS,
            use: {
                ...devices['Desktop Chrome'],
                channel: 'chromium',
                isMobile: false,
                baseURL: SCREEN_BASEURL,
            },
            dependencies: ['setup'],
        },
        {
            name: 'Screens Mobile',
            testMatch: SCREEN_TESTS,
            use: {
                ...devices['Pixel 5'],
                channel: 'chromium',
                isMobile: true,
                baseURL: SCREEN_BASEURL,
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
    webServer: KEYCLOAK_E2E
        ? {
            // Keycloak のテストは dev サーバーだけを使う (preview のビルドは不要)。起動済みならそれを使う。
            command: 'npm run dev',
            url: KEYCLOAK_BASEURL,
            reuseExistingServer: true,
        }
        : [
            {
                command: 'npm run preview',
                url: BASEURL,
                // reuseExistingServer: !process.env.CI,
            },
            {
                // 新しい画面の E2E (Screens *) が使う dev サーバー。起動済みならそれを使う。
                command: 'npm run dev',
                url: SCREEN_BASEURL,
                reuseExistingServer: true,
            },
        ],
});


/**
 * 環境変数をファイルから読み込む。
 * https://github.com/motdotla/dotenv
 */
// require('dotenv').config();