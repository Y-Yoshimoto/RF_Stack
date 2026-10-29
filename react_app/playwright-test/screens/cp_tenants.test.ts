/**
 * CP (コントロールプレーン) のテナント管理の E2E (開発用ログインで認証。01 §6・§11.2)。
 *
 * 前提: fastapi_app / keycloak_c / redis_c / postgres_c が起動し、シード (alpha / beta テナントと開発用ユーザー) が投入済みであること。
 * テナントの作成は Keycloak のレルムを実際に作る (同期で最大 30 秒ほどかかる)。作ったテナントは「削除を要求」まで進めるが、物理削除はテストでは行わない。
 * 使い捨てのテナントコードは `e2e-` + 乱数で、実行ごとに異なる。テストが途中で失敗した場合も含め、実行後に cleanup.teardown.ts (開発専用の後片付け API) が物理削除する。
 */
import { CP_HOME_PATH, CP_TENANT_CREATE_PATH, CP_TENANTS_PATH, uniqueSuffix } from '../constants';
import { test, expect } from '../fixtures';

// 払い出し (レルム作成) は同期で実行され、最大 30 秒ほどかかる
const PROVISIONING_TIMEOUT_MS = 90_000;

test.describe('CP: テナント管理 (cp-admin)', () => {
    test('テナントを作成し、一時パスワードのダイアログを閉じると消え、詳細で停止・再開・削除要求ができる', async ({ openAs }) => {
        test.setTimeout(180_000);
        const page = await openAs('cp-admin');
        const tenant_code = `e2e-${uniqueSuffix()}`;
        const tenant_name = `E2E ${tenant_code}`;
        // 残ったテナントを後で把握できるよう、レポートにも記録する
        test.info().annotations.push({ type: 'tenant_code', description: tenant_code });
        console.log(`[e2e] 使い捨てテナント: ${tenant_code}`);

        // 一覧の「テナントを作成」から作成画面へ (saas_admin にだけ出る)
        await page.goto(CP_TENANTS_PATH);
        await expect(page.getByTestId('cp-tenant-list-page')).toHaveAttribute('data-can-write', 'true');
        await page.getByTestId('tenant-list-create').click();
        await expect(page.getByTestId('cp-tenant-create-page')).toBeVisible();

        await page.getByTestId('tenant-create-tenant-code').fill(tenant_code);
        await page.getByTestId('tenant-create-name').fill(tenant_name);
        await page.getByTestId('tenant-create-email').fill(`admin@${tenant_code}.example.com`);
        await page.getByTestId('tenant-create-last-name').fill('E2E');
        await page.getByTestId('tenant-create-first-name').fill('Admin');
        await page.getByTestId('tenant-create-submit').click();

        // 一時パスワードは一度だけダイアログに表示される
        const dialog = page.getByTestId('credentials-dialog');
        await expect(dialog).toBeVisible({ timeout: PROVISIONING_TIMEOUT_MS });
        await expect(page.getByTestId('credentials-dialog-tenant-code')).toHaveText(tenant_code);
        await expect(page.getByTestId('credentials-dialog-password')).not.toBeEmpty();

        // 閉じると消え、作成したテナントの詳細へ移る
        await page.getByTestId('credentials-dialog-close').click();
        await expect(dialog).toHaveCount(0);
        await expect(page).toHaveURL(/\/cp\/tenants\/[^/]+$/);
        await expect(page.getByTestId('credentials-dialog-password')).toHaveCount(0);
        await expect(page.getByTestId('tenant-detail-code')).toHaveText(tenant_code);
        await expect(page.getByTestId('tenant-detail-status')).toHaveAttribute('data-status', 'ACTIVE');

        // 再読み込みしても、一時パスワードは再表示されない
        await page.reload();
        await expect(page.getByTestId('tenant-detail-code')).toHaveText(tenant_code);
        await expect(page.getByTestId('credentials-dialog')).toHaveCount(0);

        // 停止 -> 再開
        await page.getByTestId('tenant-action-suspend').click();
        await page.getByTestId('tenant-suspend-dialog-confirm').click();
        await expect(page.getByTestId('tenant-detail-status')).toHaveAttribute('data-status', 'SUSPENDED');
        await expect(page.getByTestId('tenant-action-suspend')).toHaveCount(0);

        await page.getByTestId('tenant-action-resume').click();
        await page.getByTestId('tenant-resume-dialog-confirm').click();
        await expect(page.getByTestId('tenant-detail-status')).toHaveAttribute('data-status', 'ACTIVE');

        // 削除要求: テナントコードを入力するまで実行できない
        await page.getByTestId('tenant-action-delete').click();
        await expect(page.getByTestId('tenant-delete-dialog-confirm')).toBeDisabled();
        await page.getByTestId('tenant-delete-confirm-input').fill(tenant_code);
        await page.getByTestId('tenant-delete-dialog-confirm').click();
        await expect(page.getByTestId('tenant-detail-status')).toHaveAttribute('data-status', 'PENDING_DELETION');
        await expect(page.getByTestId('tenant-detail-deletion-requested-at')).toBeVisible();
        await expect(page.getByTestId('tenant-detail-no-actions')).toBeVisible();

        // 一覧にも削除待ちとして表示される (既定の並びは作成日時の降順で、作ったテナントは先頭付近にある)
        await page.getByTestId('tenant-detail-back').click();
        await expect(page.getByTestId(`tenant-status-${tenant_code}`)).toHaveAttribute('data-status', 'PENDING_DELETION');
    });
});

test.describe('CP: テナント管理 (cp-viewer)', () => {
    test('一覧・詳細は見られるが、作成・操作の UI は無く、作成画面は NotFound になる', async ({ openAs }) => {
        const page = await openAs('cp-viewer');

        // 一覧: 閲覧できるが「テナントを作成」は無い (使い捨てテナントが増えても alpha が先頭ページに出るよう、コードの昇順にする)
        await page.goto(`${CP_TENANTS_PATH}?sort=tenant_code`);
        await expect(page.getByTestId('cp-tenant-list-page')).toHaveAttribute('data-can-write', 'false');
        await expect(page.getByTestId('tenant-table')).toBeVisible();
        await expect(page.getByTestId('tenant-list-create')).toHaveCount(0);

        // 詳細: 基本情報は見られるが、停止・再開・削除要求の操作は無く、閲覧専用の案内が出る
        await page.getByTestId('tenant-link-alpha').click();
        await expect(page.getByTestId('cp-tenant-detail-page')).toHaveAttribute('data-can-write', 'false');
        await expect(page.getByTestId('tenant-detail-code')).toHaveText('alpha');
        await expect(page.getByTestId('tenant-detail-viewer-notice')).toBeVisible();
        await expect(page.getByTestId('tenant-detail-actions')).toHaveCount(0);
        await expect(page.getByTestId('tenant-action-suspend')).toHaveCount(0);
        await expect(page.getByTestId('tenant-action-delete')).toHaveCount(0);

        // 作成画面を URL で直接開いても、フォームは出ない (NotFound)
        await page.goto(CP_TENANT_CREATE_PATH);
        await expect(page.getByTestId('not-found-page')).toBeVisible();
        await expect(page.getByTestId('cp-tenant-create-page')).toHaveCount(0);
        await page.getByTestId('not-found-home-link').click();
        await expect(page).toHaveURL(CP_HOME_PATH);
    });
});
