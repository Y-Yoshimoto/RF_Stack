/**
 * AP のユーザー作成の E2E (開発用ログインで認証。01 §8)。
 *
 * 注意: ユーザーの作成は Keycloak (tenant-alpha レルム) に実ユーザーを作る。ユーザーは削除できないため、テストは作成したユーザーを必ず無効化する
 * (画面の「無効にする」。途中で失敗した場合は finally で API から無効化する)。無効なユーザーの行は alpha の DB と Keycloak に残る
 * (メールアドレスは `e2e-` + 乱数 @example.com で、実行ごとに異なる)。
 */
import { appPath, uniqueSuffix } from '../constants';
import { test, expect } from '../fixtures';
import { cleanupDeactivateUser } from '../helpers/api';

test.describe('AP: ユーザー (alpha-admin)', () => {
    test('ユーザーを作成し、一時パスワードのダイアログを閉じると消え、詳細から無効化できる', async ({ openAs }) => {
        const page = await openAs('alpha-admin');
        const suffix = uniqueSuffix();
        const email = `e2e-${suffix}@example.com`;
        console.log(`[e2e] 作成するユーザー (テストの最後に無効化する): ${email}`);

        try {
            await page.goto(appPath('users'));
            await expect(page.getByTestId('app-user-list-page')).toHaveAttribute('data-can-write', 'true');
            await page.getByTestId('user-list-create').click();
            await expect(page.getByTestId('app-user-create-page')).toHaveAttribute('data-can-write', 'true');

            await page.getByTestId('user-create-email').fill(email);
            await page.getByTestId('user-create-last-name').fill('E2E');
            await page.getByTestId('user-create-first-name').fill(suffix);
            await expect(page.getByTestId('user-create-role-member')).toBeChecked();
            await page.getByTestId('user-create-submit').click();

            // 一時パスワードは一度だけダイアログに表示される
            const dialog = page.getByTestId('credentials-dialog');
            await expect(dialog).toBeVisible();
            await expect(page.getByTestId('credentials-dialog-password')).not.toBeEmpty();
            await page.getByTestId('credentials-dialog-close').click();
            await expect(dialog).toHaveCount(0);
            await expect(page.getByTestId('credentials-dialog-password')).toHaveCount(0);
            await expect(page.getByTestId('user-create-done')).toContainText('再表示はできません');

            // 詳細を開いて有効なことを確認し、無効化する (確認ダイアログ)
            await page.getByTestId('user-create-done-detail').click();
            await expect(page.getByTestId('user-info-email')).toHaveText(email);
            await expect(page.getByTestId('user-info-status')).toContainText('有効');
            await page.getByTestId('user-deactivate').click();
            await page.getByTestId('user-deactivate-dialog-confirm').click();
            await expect(page.getByTestId('user-reactivate')).toBeVisible();
            await expect(page.getByTestId('user-info-status')).toContainText('無効');
        } finally {
            await cleanupDeactivateUser(page.request, email);
        }
    });
});
