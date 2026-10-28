/**
 * 認証状態のセットアップ。
 *
 * 開発用ログインバイパス (`/api/auth/dev-login`) で 1 回だけログインし、
 * 得られたセッション Cookie を storageState として保存する。
 * 各テストはこの状態から始まるため、テストごとに認証をやり直さずに済む。
 *
 * ロール別のテストを追加する場合は、プロファイルと出力先を変えた setup を増やし、
 * playwright.config.ts に対応する project を足す。
 */
import { test as setup, expect } from '@playwright/test';
import { APP_HOME_PATH, DEV_PROFILE, TENANT_CODE } from './constants';

/**
 * 認証状態の保存先。playwright.config.ts の storageState と対応させる。
 * package.json が type=module のため __dirname は使えない。
 * playwright の実行ディレクトリ (react_app) からの相対パスで指定する。
 */
export const AUTH_STATE_FILE = './playwright-test/.auth/default.json';

setup('開発用ログインで認証状態を作成する', async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL });

    // リダイレクト先はフロントエンドの FRONTEND_URL (別ポート) になるため追従しない。
    // ここで必要なのは Set-Cookie によるセッション Cookie のみ。
    const response = await context.request.get(`/api/auth/dev-login?as=${DEV_PROFILE}`, {
        maxRedirects: 0,
    });

    if (response.status() !== 302) {
        const body = await response.text().catch(() => '');
        throw new Error(
            [
                `開発用ログインに失敗しました (HTTP ${response.status()})。`,
                '次を確認してください:',
                '  - docker compose up -d で fastapi_app / keycloak_c / redis_c が起動しているか',
                '  - AUTH_DEV_LOGIN_ENABLED=true かつ APP_ENV=development か',
                '  - KeyCloak の client で directAccessGrantsEnabled が有効か',
                '  - シードで tenant-alpha レルムと alpha-admin ユーザーが作成済みか',
                `応答: ${body.slice(0, 200)}`,
            ].join('\n'),
        );
    }

    // ログイン成功後の遷移先は AP のホーム (/{tenant_code}/。FastAPI: modules/auth/redirects.py)
    const location = new URL(response.headers()['location'] ?? '', 'http://placeholder');
    expect(location.pathname, 'dev-login のリダイレクト先が AP のホームではありません').toBe(APP_HOME_PATH);

    // セッションが実際に有効であることを確認してから保存する
    // alpha-admin プロファイルはアプリケーションプレーン (Cookie rf_sid_app) のセッションを作る
    const status_response = await context.request.get('/api/auth/app/status');
    expect(status_response.ok()).toBeTruthy();
    const status = await status_response.json();
    expect(status.authenticated).toBe(true);
    // AP のルートガードは URL のテナントコードとセッションのテナントコードを照合する
    expect(status.tenant_code).toBe(TENANT_CODE);

    await context.storageState({ path: AUTH_STATE_FILE });
    await context.close();
});
