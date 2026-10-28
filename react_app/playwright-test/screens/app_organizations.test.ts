/**
 * AP (アプリケーションプレーン) の組織管理の E2E (開発用ログインで認証。01 §8)。
 *
 * 前提: fastapi_app / keycloak_c / redis_c / postgres_c が起動し、シードが投入済みであること。
 * テストが作る組織は `E2E Org` + 乱数の名前で、テストの最後に画面 (または失敗時は API) で削除する。
 */
import { appPath, uniqueSuffix } from '../constants';
import { test, expect } from '../fixtures';
import { cleanupDeleteOrganizations, createOrganization, findUserByEmail } from '../helpers/api';

const MEMBER_EMAIL = 'alpha-member@example.com';

test.describe('AP: 組織 (alpha-admin)', () => {
    test('組織を作成し、メンバーを設定して、削除できる', async ({ openAs }) => {
        const page = await openAs('alpha-admin');
        const name = `E2E Org ${uniqueSuffix()}`;

        try {
            // 作成 (一覧のダイアログ)
            await page.goto(appPath('organizations'));
            await expect(page.getByTestId('app-organization-list-page')).toHaveAttribute('data-can-write', 'true');
            await page.getByTestId('organization-list-create').click();
            await page.getByTestId('organization-create-name').fill(name);
            await page.getByTestId('organization-create-submit').click();
            await expect(page.getByTestId('organization-list-notice')).toContainText(name);
            const link = page.getByRole('link', { name, exact: true });
            await expect(link).toBeVisible();

            // 詳細でメンバーを設定する (alpha-member を追加)
            await link.click();
            await expect(page.getByTestId('organization-detail-title')).toHaveText(name);
            await expect(page.getByTestId('organization-members-save')).toBeDisabled();
            await page.getByTestId('organization-members-input').fill(MEMBER_EMAIL);
            await page.getByRole('option', { name: new RegExp(MEMBER_EMAIL.replace('.', '\\.')) }).click();
            await page.getByTestId('organization-members-save').click();
            await expect(page.getByTestId('organization-detail-notice')).toHaveText('メンバーを保存しました。');

            // 再読み込みしてもメンバーが保存されている
            await page.reload();
            await expect(page.getByRole('heading', { name: 'メンバー (1 人)' })).toBeVisible();
            await expect(page.getByTestId('organization-members-select')).toContainText(MEMBER_EMAIL);

            // 削除 (確認ダイアログ)。一覧に戻り、組織は消えている
            await page.getByTestId('organization-delete').click();
            await page.getByTestId('organization-delete-dialog-confirm').click();
            await expect(page).toHaveURL(appPath('organizations'));
            await expect(page.getByTestId('app-organization-list-page')).toBeVisible();
            await expect(page.getByRole('link', { name, exact: true })).toHaveCount(0);
        } finally {
            await cleanupDeleteOrganizations(page.request, name);
        }
    });
});

test.describe('AP: 組織・ユーザー (alpha-member は閲覧のみ)', () => {
    test('組織・ユーザーの一覧と詳細を見られるが、作成・編集の UI は無く、ユーザー作成画面は使えない', async ({ openAs }) => {
        const admin = await openAs('alpha-admin');
        const name = `E2E Org ${uniqueSuffix()}`;
        const member = await findUserByEmail(admin.request, MEMBER_EMAIL);
        expect(member, `${MEMBER_EMAIL} がシードされていません`).not.toBeNull();
        const organization = await createOrganization(admin.request, name, [member!.id]);

        try {
            const page = await openAs('alpha-member');

            // 組織の一覧: 作成・削除の UI は無く、閲覧のみの案内が出る
            await page.goto(appPath('organizations'));
            await expect(page.getByTestId('app-organization-list-page')).toHaveAttribute('data-can-write', 'false');
            await expect(page.getByTestId('organization-list-readonly')).toBeVisible();
            await expect(page.getByTestId('organization-list-create')).toHaveCount(0);
            await expect(page.getByTestId(`organization-delete-${organization.id}`)).toHaveCount(0);

            // 組織の詳細: メンバーは一覧で見られるが、名前の変更・メンバーの設定・削除は無い
            await page.getByTestId(`organization-link-${organization.id}`).click();
            await expect(page.getByTestId('organization-detail-title')).toHaveText(name);
            await expect(page.getByTestId('organization-detail-readonly')).toBeVisible();
            await expect(page.getByTestId(`organization-member-${member!.id}`)).toBeVisible();
            await expect(page.getByTestId('organization-rename-submit')).toHaveCount(0);
            await expect(page.getByTestId('organization-members-save')).toHaveCount(0);
            await expect(page.getByTestId('organization-delete')).toHaveCount(0);

            // プロフィールの所属組織に表示される
            await page.goto(appPath('profile'));
            await expect(page.getByTestId('profile-username')).toHaveText('alpha-member');
            await expect(page.getByTestId(`profile-organization-${organization.id}`)).toHaveText(name);

            // ユーザーの一覧: 作成の導線は無い。作成画面を URL で開いても権限が必要な旨だけが出る
            await page.goto(appPath('users'));
            await expect(page.getByTestId('app-user-list-page')).toHaveAttribute('data-can-write', 'false');
            await expect(page.getByTestId('user-list-readonly')).toBeVisible();
            await expect(page.getByTestId('user-list-create')).toHaveCount(0);
            await page.goto(appPath('users/new'));
            await expect(page.getByTestId('user-create-forbidden')).toBeVisible();
            await expect(page.getByTestId('user-create-form')).toHaveCount(0);
        } finally {
            await cleanupDeleteOrganizations(admin.request, name);
        }
    });
});
