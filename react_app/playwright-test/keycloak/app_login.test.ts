/**
 * AP (アプリケーションプレーン) の Keycloak 経由のログイン E2E。
 *
 * 開発用ログイン (dev-login) を使わず、Keycloak のログインフォーム (keycloak_c の実画面) を通る。
 * 前提: docker compose up -d で fastapi_app / keycloak_c / redis_c が起動し、シード
 * (alpha / beta テナントと開発用ユーザー) が投入済みであること。実行は playwright.config.ts の
 * 'Keycloak Desktop' / 'Keycloak Mobile' プロジェクト (npm run playwright:keycloak。run-checks スキル §5)。Keycloak のユーザーは参照のみで、作成・変更しない。
 *
 * ログイン後の初回はユーザー同期でユーザー行が作られうるが、テストは DB の状態に依存せず画面とステータス API だけを見る。
 */
import { test, expect } from '@playwright/test';
import { DEV_ACCOUNTS, WRONG_PASSWORD, devPassword } from './dev_credentials';
import { KeycloakLoginPage } from './pages/keycloak_login_page';

const ALPHA = DEV_ACCOUNTS.alpha_admin.tenant_code;
const BETA = DEV_ACCOUNTS.beta_member.tenant_code;

test.describe('AP: Keycloak 経由のログイン', () => {
    test('テナントコードを入力してログインし、ホームにユーザー名が表示され、ログアウトでログイン画面に戻る', async ({ page }) => {
        const keycloak = new KeycloakLoginPage(page);

        // ランディングでテナントコードを入力する
        await page.goto('/');
        await page.getByTestId('login-tenant-code').fill(ALPHA);
        await page.getByTestId('login-submit').click();
        // 同じ login-submit が使われているため、ログイン画面の描画を待ってから押す
        await expect(page.getByTestId('app-login-page')).toBeVisible();

        // ログインボタン → Keycloak (tenant-alpha レルム)
        await page.getByTestId('login-submit').click();
        await keycloak.expectShown(`tenant-${ALPHA}`);
        await keycloak.submitCredentials(DEV_ACCOUNTS.alpha_admin.username, devPassword());

        // アプリのホームに戻り、ログイン中のユーザー名が出る
        await expect(page).toHaveURL(`/${ALPHA}/`);
        await expect(page.getByTestId('app-home-page')).toBeVisible();
        await expect(page.getByTestId('app-home-user')).toHaveText(DEV_ACCOUNTS.alpha_admin.username);

        // ログアウトでログイン画面に戻り、セッションは無効になっている
        await page.getByTestId('logout-button').click();
        await expect(page).toHaveURL(`/${ALPHA}/login`);
        await expect(page.getByTestId('app-login-page')).toBeVisible();
        const status = await page.request.get('/api/auth/app/status');
        expect(status.status()).toBe(401);
    });

    test('誤ったパスワードでは Keycloak がエラーを表示し、アプリに入れない', async ({ page }) => {
        const keycloak = new KeycloakLoginPage(page);

        await page.goto(`/${ALPHA}/login`);
        await page.getByTestId('login-submit').click();
        await keycloak.expectShown(`tenant-${ALPHA}`);
        await keycloak.submitCredentials(DEV_ACCOUNTS.alpha_member2.username, WRONG_PASSWORD);
        await keycloak.expectLoginFailed();

        // アプリのセッションは作られていない (ホームを開いてもログイン画面に戻される)
        await page.goto(`/${ALPHA}/`);
        await expect(page).toHaveURL(`/${ALPHA}/login`);
        await expect(page.getByTestId('app-login-page')).toBeVisible();
    });

    test('別テナントでログイン中に他テナントのホームを開くと「別テナントでログイン中」のエラーになる', async ({ page }) => {
        const keycloak = new KeycloakLoginPage(page);

        // beta-member で beta にログインする
        await page.goto(`/${BETA}/login`);
        await page.getByTestId('login-submit').click();
        await keycloak.expectShown(`tenant-${BETA}`);
        await keycloak.submitCredentials(DEV_ACCOUNTS.beta_member.username, devPassword());
        await expect(page).toHaveURL(`/${BETA}/`);
        await expect(page.getByTestId('app-home-user')).toHaveText(DEV_ACCOUNTS.beta_member.username);

        // alpha のホーム・ログイン画面を開くと mismatch のエラー画面になる (ホームの内容は出ない)
        for (const path of [`/${ALPHA}/`, `/${ALPHA}/login`]) {
            await page.goto(path);
            await expect(page.getByTestId('tenant-error-page')).toHaveAttribute('data-kind', 'mismatch');
            await expect(page.getByTestId('app-home-page')).toHaveCount(0);
        }

        // 後始末: ログアウトできる (セッションはブラウザコンテキストごとに破棄されるが、サーバー側のセッションも残さない)
        await page.getByTestId('tenant-error-logout').click();
        await expect(page.getByTestId('app-login-page')).toBeVisible();
    });
});

test.describe('AP: 利用できないテナントコード', () => {
    test('存在しないテナントコードはランディングで入力するとログイン画面でテナント不在のエラーになる', async ({ page }) => {
        await page.goto('/');
        await page.getByTestId('login-tenant-code').fill('nosuch');
        await page.getByTestId('login-submit').click();
        await expect(page).toHaveURL('/nosuch/login');
        await expect(page.getByTestId('tenant-error-page')).toHaveAttribute('data-kind', 'not_found');
        // ログインボタンは出ない
        await expect(page.getByTestId('login-submit')).toHaveCount(0);
    });

    test('存在しないテナントコードでログインを開始するとランディングに戻りエラーが表示される', async ({ page }) => {
        // ログイン画面を経由せず BFF のログイン開始を直接呼ぶ (フロントの事前確認をすり抜けた場合の確認)
        await page.goto('/api/auth/app/login?tenant_code=nosuch');
        await expect(page).toHaveURL('/?error=tenant_unavailable');
        await expect(page.getByTestId('login-error')).toHaveAttribute('data-code', 'tenant_unavailable');
    });

    test('予約語はランディングで入力するとエラーが表示され、ログイン画面へ進まない', async ({ page }) => {
        await page.goto('/');
        await page.getByTestId('login-tenant-code').fill('admin');
        await page.getByTestId('login-submit').click();
        await expect(page.getByTestId('tenant-code-violation')).toBeVisible();
        await expect(page).toHaveURL('/');
    });

    test('予約語のパスはテナントのログイン画面として開けない', async ({ page }) => {
        await page.goto('/admin/login');
        await expect(page.getByTestId('not-found-page')).toBeVisible();
        await expect(page.getByTestId('login-submit')).toHaveCount(0);
    });
});
