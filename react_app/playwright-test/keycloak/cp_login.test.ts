/**
 * CP (コントロールプレーン) の Keycloak 経由のログイン E2E。
 *
 * 開発用ログイン (dev-login) を使わず、control-plane レルムの Keycloak ログインフォーム (実画面) を通る。
 * 前提・実行方法は app_login.test.ts を参照。Keycloak のユーザーは参照のみで、作成・変更しない。
 */
import { test, expect } from '@playwright/test';
import { DEV_ACCOUNTS, devPassword } from './dev_credentials';
import { KeycloakLoginPage } from './pages/keycloak_login_page';

const CP_REALM = 'control-plane';

test.describe('CP: Keycloak 経由のログイン', () => {
    test('cp-viewer でログインすると CP のホームに入れるが、変更操作はできない', async ({ page }) => {
        const keycloak = new KeycloakLoginPage(page);

        await page.goto('/cp/login');
        await page.getByTestId('login-submit').click();
        await keycloak.expectShown(CP_REALM);
        await keycloak.submitCredentials(DEV_ACCOUNTS.cp_viewer.username, devPassword());

        await expect(page).toHaveURL('/cp/');
        await expect(page.getByTestId('cp-home-user')).toHaveText(DEV_ACCOUNTS.cp_viewer.username);
        // saas_viewer は参照のみ (変更操作の UI を出さない判定が偽になる)
        await expect(page.getByTestId('cp-home-page')).toHaveAttribute('data-can-write', 'false');

        // ログアウトで CP のログイン画面に戻る
        await page.getByTestId('logout-button').click();
        await expect(page).toHaveURL('/cp/login');
        await expect(page.getByTestId('cp-login-page')).toBeVisible();
    });

    test('cp-admin でログインすると変更操作ができる', async ({ page }) => {
        const keycloak = new KeycloakLoginPage(page);

        await page.goto('/cp/login');
        await page.getByTestId('login-submit').click();
        await keycloak.expectShown(CP_REALM);
        await keycloak.submitCredentials(DEV_ACCOUNTS.cp_admin.username, devPassword());

        await expect(page).toHaveURL('/cp/');
        await expect(page.getByTestId('cp-home-user')).toHaveText(DEV_ACCOUNTS.cp_admin.username);
        await expect(page.getByTestId('cp-home-page')).toHaveAttribute('data-can-write', 'true');
    });
});
