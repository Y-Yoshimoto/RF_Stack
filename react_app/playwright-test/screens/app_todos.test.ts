/**
 * AP の ToDo の E2E (開発用ログインで認証。docs/spec/ToDoApp.md)。
 *
 * 1 つのシナリオに 3 人が登場する: alpha-admin (作成・削除)、alpha-member (担当者)、beta-member (別テナント)。
 * 前提: fastapi_app / keycloak_c / redis_c / postgres_c が起動し、シードが投入済みであること。
 * テストが作る ToDo は `E2E ToDo` + 乱数のタイトルで、画面から削除する (論理削除)。公開先にする組織は前提データとして API で作る。
 * 途中で失敗した場合も含め、実行後に cleanup.teardown.ts (開発専用の後片付け API) が ToDo・組織を物理削除する。
 */
import { appPath, TENANT_CODE, uniqueSuffix } from '../constants';
import { test, expect } from '../fixtures';
import { createOrganization, findUserByEmail } from '../helpers/api';

const MEMBER_EMAIL = 'alpha-member@example.com';

test.describe('AP: ToDo', () => {
    test('admin が組織公開・担当者付きで作成し、担当者の member がステータスだけ変更でき、別テナントからは開けず、admin が削除する', async ({ openAs }) => {
        const admin = await openAs('alpha-admin');
        const suffix = uniqueSuffix();
        const title = `E2E ToDo ${suffix}`;
        const organization_name = `E2E Org ${suffix}`;
        const member = await findUserByEmail(admin.request, MEMBER_EMAIL);
        expect(member, `${MEMBER_EMAIL} がシードされていません`).not.toBeNull();
        const organization = await createOrganization(admin.request, organization_name);

        // alpha-admin: 組織公開・担当者 (alpha-member) 付きで作成する -> 詳細へ遷移
        await admin.goto(appPath('todos/new'));
        await admin.getByTestId('todo-create-field-title').fill(title);
        await admin.getByTestId('todo-create-field-description').fill('E2E で作成した ToDo');
        await admin.getByTestId('todo-create-audience-visibility-organization').check();
        await admin.getByTestId(`todo-create-audience-organization-${organization.id}`).check();
        await admin.getByTestId('todo-create-assignees-input').fill(member!.display_name);
        await admin.getByRole('option', { name: member!.display_name, exact: true }).click();
        await admin.getByTestId('todo-create-submit').click();
        await expect(admin).toHaveURL(/\/todos\/(?!new)[^/]+$/);
        const todo_id = new URL(admin.url()).pathname.split('/').pop()!;
        await expect(admin.getByTestId('todo-detail-title')).toHaveText(title);
        await expect(admin.getByTestId('todo-detail-status-chip')).toHaveAttribute('data-status', 'open');

        // alpha-member: 「自分が担当」タブで見つけ、一覧からステータスを変更できる
        const member_page = await openAs('alpha-member');
        await member_page.goto(appPath('todos'));
        await member_page.getByTestId('todo-scope-assigned').click();
        await expect(member_page.getByTestId('app-todo-list-page')).toHaveAttribute('data-scope', 'assigned');
        // md 以上は表の行 (todo-row-)、md 未満 (モバイル) はカード (todo-card-)
        const row = member_page.getByTestId(new RegExp(`^todo-(row|card)-${todo_id}$`));
        await expect(row).toContainText(title);
        await expect(row).toHaveAttribute('data-status', 'open');
        await member_page.getByTestId(`todo-status-select-${todo_id}`).getByRole('combobox').click();
        await member_page.getByTestId(`todo-status-option-${todo_id}-in_progress`).click();
        await expect(member_page.getByTestId('todo-list-notice')).toContainText('進行中');
        await expect(row).toHaveAttribute('data-status', 'in_progress');

        // alpha-member: 詳細ではタイトルを編集できないが、ステータスは変更できる。削除はできない
        await member_page.getByTestId(`todo-link-${todo_id}`).click();
        await expect(member_page.getByTestId('todo-detail-title')).toHaveText(title);
        await expect(member_page.getByTestId('todo-fields-readonly')).toBeVisible();
        await expect(member_page.getByTestId('todo-edit-title')).toBeDisabled();
        await expect(member_page.getByTestId('todo-fields-submit')).toHaveCount(0);
        await expect(member_page.getByTestId('todo-detail-delete')).toHaveCount(0);
        await member_page.getByTestId('todo-status-done').click();
        await expect(member_page.getByTestId('todo-detail-status-chip')).toHaveAttribute('data-status', 'done');

        // beta-member: alpha の ToDo の URL を開くと、別テナントでログイン中のエラーになる
        const beta_page = await openAs('beta-member');
        await beta_page.goto(appPath(`todos/${todo_id}`, TENANT_CODE));
        await expect(beta_page.getByTestId('tenant-error-page')).toHaveAttribute('data-kind', 'mismatch');
        await expect(beta_page.getByTestId('app-todo-detail-page')).toHaveCount(0);

        // alpha-admin: 担当者の変更が反映された詳細から削除する
        await admin.reload();
        await expect(admin.getByTestId('todo-detail-status-chip')).toHaveAttribute('data-status', 'done');
        await admin.getByTestId('todo-detail-delete').click();
        await admin.getByTestId('todo-delete-dialog-confirm').click();
        await expect(admin).toHaveURL(appPath('todos'));
        await expect(admin.getByTestId('todo-list-notice')).toContainText(title);
        await expect(admin.getByTestId(new RegExp(`^todo-(row|card)-${todo_id}$`))).toHaveCount(0);

        // 削除後は担当者からも見えない (404)
        await member_page.goto(appPath(`todos/${todo_id}`));
        await expect(member_page.getByTestId('todo-detail-error')).toBeVisible();
    });
});
