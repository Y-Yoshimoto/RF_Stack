/**
 * AP の ToDo の共同作業の E2E (開発用ログインで認証。docs/spec/ToDoApp.md v0.6 §4.5 コメント・§4.6 チェックリスト・§4.7 カンバン・§4.8 AP-UX)。
 *
 * 登場する利用者: alpha-admin (作成者・テナント管理者)、alpha-member (担当者。担当でない ToDo では閲覧だけの利用者)、beta-member (別テナント)。
 * 前提: fastapi_app / keycloak_c / redis_c / postgres_c が起動し、シードが投入済みであること。
 * ToDo は API で用意し (前提データ)、画面で検証したい操作だけを画面で行う。タイトルは `E2E ToDo <8 文字>` で、コメント・チェック項目は ToDo と一緒に
 * 実行後に cleanup.teardown.ts (開発専用の後片付け API) が物理削除する。個別の後片付けは書かない。
 * 閲覧だけの利用者には、開発用ログインのプロファイルを持つ alpha-member を使う (alpha-member2 はシードされるがプロファイルが無い)。
 * ToDo を tenant 公開にして担当者にしなければ、alpha-member は作成者でも担当者でもない利用者になる。
 */
import type { Locator, Page } from '@playwright/test';
import { appPath, TENANT_CODE, uniqueSuffix } from '../constants';
import { test, expect } from '../fixtures';
import { createChecklistItem, createComment, createTodo, CSRF_HEADERS, fetchTodo, findUserByEmail } from '../helpers/api';

const MEMBER_EMAIL = 'alpha-member@example.com';

/** UUID (ID を含む data-testid の正規表現に使う) */
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
/** チェックリストの 1 行 / 項目名 */
const CHECKLIST_ROW = new RegExp(`^todo-checklist-item-${UUID}$`);
const CHECKLIST_TITLE = new RegExp(`^todo-checklist-item-${UUID}-title$`);
/** コメントの 1 件 */
const COMMENT_ITEM = new RegExp(`^todo-comment-${UUID}$`);

/** 使い捨ての ToDo のタイトル (後片付けの対象の命名。完全一致で判定されるため接尾辞を付け足さない) */
const newTitle = (): string => `E2E ToDo ${uniqueSuffix()}`;

/** alpha-member のユーザー ID を返す */
async function memberIdOf(page: Page): Promise<string> {
    const member = await findUserByEmail(page.request, MEMBER_EMAIL);
    expect(member, `${MEMBER_EMAIL} がシードされていません`).not.toBeNull();
    return member!.id;
}

/** チェックリストの項目名で行を探す */
const checklistRowOf = (page: Page, title: string): Locator => page.getByTestId(CHECKLIST_ROW).filter({ hasText: title });

/**
 * 本文で見つけたコメントを、ID で指す Locator にする (編集中は本文が textarea に替わり、本文での絞り込みに合わなくなるため)
 */
async function commentByBody(page: Page, body: string): Promise<Locator> {
    const found = page.getByTestId(COMMENT_ITEM).filter({ hasText: body });
    await expect(found).toBeVisible();
    return page.getByTestId((await found.getAttribute('data-testid'))!);
}

/** 入力中のコメントを投稿ボタンで投稿する */
async function postComment(page: Page): Promise<void> {
    await page.getByTestId('todo-comment-submit').click();
}

/** 一覧 (表の行 / カード) の要素。md 以上は表、md 未満はカード */
const listItemOf = (page: Page, todo_id: string): Locator => page.getByTestId(new RegExp(`^todo-(row|card)-${todo_id}$`));

/** ToDo の詳細を開き、表示を待つ */
async function openDetail(page: Page, todo_id: string, title: string): Promise<void> {
    await page.goto(appPath(`todos/${todo_id}`));
    await expect(page.getByTestId('todo-detail-title')).toHaveText(title);
}

test.describe('AP: ToDo のチェックリスト', () => {
    test('admin が項目を追加・名前変更・並べ替えし、担当者の member はチェックだけできて、進捗の表示が変わる', async ({ openAs }) => {
        const admin = await openAs('alpha-admin');
        const title = newTitle();
        const todo = await createTodo(admin.request, { title, visibility: 'tenant', assignee_ids: [await memberIdOf(admin)] });

        // alpha-admin: 項目を追加する (Enter で続けて入力できる)
        await openDetail(admin, todo.id, title);
        await expect(admin.getByTestId('todo-checklist-empty')).toBeVisible();
        for (const item_title of ['準備', '実行', '確認']) {
            await admin.getByTestId('todo-checklist-add-input').fill(item_title);
            await admin.getByTestId('todo-checklist-add-input').press('Enter');
            await expect(checklistRowOf(admin, item_title)).toBeVisible();
        }
        const titles = admin.getByTestId(CHECKLIST_TITLE);
        await expect(titles).toHaveText(['準備', '実行', '確認']);
        await expect(admin.getByTestId('todo-checklist-progress-text')).toHaveText('0 / 3 完了');
        await expect(admin.getByTestId('todo-detail-checklist-progress')).toContainText('0 / 3');

        // 名前の変更 (その場編集。Enter で保存)
        await checklistRowOf(admin, '実行').getByTestId(/-edit$/).click();
        await admin.getByTestId(/-rename-input$/).fill('実施');
        await admin.getByTestId(/-rename-input$/).press('Enter');
        await expect(titles).toHaveText(['準備', '実施', '確認']);

        // 並べ替え (メニューの「上へ移動」「下へ移動」。ドラッグの代替手段)
        await checklistRowOf(admin, '確認').getByTestId(/-menu-button$/).click();
        await admin.getByRole('menuitem', { name: '上へ移動' }).click();
        await expect(titles).toHaveText(['準備', '確認', '実施']);
        await checklistRowOf(admin, '準備').getByTestId(/-menu-button$/).click();
        await admin.getByRole('menuitem', { name: '下へ移動' }).click();
        await expect(titles).toHaveText(['確認', '準備', '実施']);
        await admin.reload();
        await expect(titles).toHaveText(['確認', '準備', '実施']);

        // alpha-member (担当者): 項目の追加・名前の変更・削除・並べ替えの UI は無く、チェックだけできる
        const member = await openAs('alpha-member');
        await openDetail(member, todo.id, title);
        await expect(titles.first()).toBeVisible();
        await expect(member.getByTestId('todo-checklist-readonly')).toBeVisible();
        await expect(member.getByTestId('todo-checklist-add-form')).toHaveCount(0);
        await expect(member.getByTestId(/^todo-checklist-item-.+-handle$/)).toHaveCount(0);
        await expect(member.getByTestId(/^todo-checklist-item-.+-edit$/)).toHaveCount(0);
        await expect(member.getByTestId(/^todo-checklist-item-.+-menu-button$/)).toHaveCount(0);
        const row = checklistRowOf(member, '確認');
        // 完了の切り替えは結果を待ってから表示が変わる (制御されたチェックボックス) ため、check() ではなく click() で押す
        await row.getByTestId(/-check$/).click();
        await expect(row).toHaveAttribute('data-done', 'true');
        await expect(member.getByTestId('todo-checklist-progress-text')).toHaveText('1 / 3 完了');
        await expect(member.getByTestId('todo-detail-checklist-progress')).toContainText('1 / 3');

        // alpha-admin: 担当者のチェックが反映され、完了した人と日時が出る
        await admin.reload();
        const done_row = checklistRowOf(admin, '確認');
        await expect(done_row).toHaveAttribute('data-done', 'true');
        await expect(done_row.getByTestId(/-done-text$/)).toContainText('に完了');
        await expect(admin.getByTestId('todo-checklist-progress-text')).toHaveText('1 / 3 完了');
    });
});

test.describe('AP: ToDo のコメント', () => {
    test('member が投稿・編集 (編集済み) し、admin から見えて、admin は member のコメントを削除できるが、member は他人のコメントを削除できない', async ({ openAs, isMobile }) => {
        const admin = await openAs('alpha-admin');
        const title = newTitle();
        const todo = await createTodo(admin.request, { title, visibility: 'tenant', assignee_ids: [await memberIdOf(admin)] });

        // alpha-member: 詳細の既定のタブはコメント。投稿して、自分のコメントを編集する
        const member = await openAs('alpha-member');
        await openDetail(member, todo.id, title);
        await expect(member.getByTestId('todo-tab-comments')).toHaveText('コメント (0)');
        await expect(member.getByTestId('todo-comments-empty')).toBeVisible();
        await member.getByTestId('todo-comment-input').fill('最初のコメントです');
        await postComment(member);
        const own = await commentByBody(member, '最初のコメントです');
        await expect(member.getByTestId('todo-tab-comments')).toHaveText('コメント (1)');
        await expect(own).toHaveAttribute('data-edited', 'false');
        await own.getByTestId(/-edit$/).click();
        await own.getByTestId(/-input$/).fill('編集したコメントです');
        await own.getByTestId(/-save$/).click();
        await expect(own.getByTestId(/-body$/)).toHaveText('編集したコメントです');
        const edited = own;
        await expect(edited.getByTestId(/-edited$/)).toHaveText('編集済み');
        await expect(edited).toHaveAttribute('data-edited', 'true');

        // alpha-admin: member のコメントが見える。削除はできるが編集はできない。自分のコメントも投稿する
        await openDetail(admin, todo.id, title);
        await expect(admin.getByTestId('todo-tab-comments')).toHaveText('コメント (1)');
        const others = await commentByBody(admin, '編集したコメントです');
        await expect(others.getByTestId(/-edited$/)).toBeVisible();
        await expect(others.getByTestId(/-edit$/)).toHaveCount(0);
        await expect(others.getByTestId(/-delete$/)).toBeVisible();
        await admin.getByTestId('todo-comment-input').fill('管理者からのコメントです');
        await postComment(admin);
        await expect(admin.getByTestId(COMMENT_ITEM).filter({ hasText: '管理者からのコメントです' })).toBeVisible();

        // Ctrl + Enter でも投稿できる (画面の案内にある操作。Desktop のみ確認する)
        if (!isMobile) {
            await admin.getByTestId('todo-comment-input').fill('Ctrl + Enter で投稿したコメントです');
            await admin.getByTestId('todo-comment-input').press('Control+Enter');
            await expect(admin.getByTestId(COMMENT_ITEM).filter({ hasText: 'Ctrl + Enter で投稿したコメントです' })).toBeVisible();
            await expect(admin.getByTestId('todo-tab-comments')).toHaveText('コメント (3)');
            await admin.getByTestId(COMMENT_ITEM).filter({ hasText: 'Ctrl + Enter で投稿したコメントです' }).getByTestId(/-delete$/).click();
            await admin.getByTestId('todo-comment-delete-dialog-confirm').click();
            await expect(admin.getByTestId(COMMENT_ITEM)).toHaveCount(2);
        }

        // alpha-member: 他人 (admin) のコメントは見えるが、編集・削除の操作は出ない。自分のコメントには出る
        await member.reload();
        await expect(member.getByTestId(COMMENT_ITEM)).toHaveCount(2);
        const admins = member.getByTestId(COMMENT_ITEM).filter({ hasText: '管理者からのコメントです' });
        await expect(admins).toBeVisible();
        await expect(admins.getByTestId(/-edit$/)).toHaveCount(0);
        await expect(admins.getByTestId(/-delete$/)).toHaveCount(0);
        const mine = member.getByTestId(COMMENT_ITEM).filter({ hasText: '編集したコメントです' });
        await expect(mine.getByTestId(/-edit$/)).toBeVisible();
        await expect(mine.getByTestId(/-delete$/)).toBeVisible();

        // alpha-admin: member のコメントを確認ダイアログ経由で削除する
        await others.getByTestId(/-delete$/).click();
        await admin.getByTestId('todo-comment-delete-dialog-confirm').click();
        await expect(others).toHaveCount(0);
        await expect(admin.getByTestId('todo-tab-comments')).toHaveText('コメント (1)');
        await member.reload();
        await expect(member.getByTestId(COMMENT_ITEM)).toHaveCount(1);
        await expect(member.getByTestId(COMMENT_ITEM)).toContainText('管理者からのコメントです');
    });
});

test.describe('AP: ToDo のボード', () => {
    /** ボード表示の URL (タイトルで 1 件に絞る) */
    const boardPathOf = (title: string): string => `${appPath('todos')}?view=board&q=${encodeURIComponent(title)}`;

    /** カードのメニュー (ドラッグの代替手段) でステータスを変える */
    async function moveViaMenu(page: Page, todo_id: string, status: 'open' | 'in_progress' | 'done'): Promise<void> {
        await page.getByTestId(`todo-board-menu-${todo_id}`).click();
        await page.getByTestId(`todo-status-select-${todo_id}`).getByRole('combobox').click();
        await page.getByTestId(`todo-status-option-${todo_id}-${status}`).click();
    }

    /** マウスでハンドルを掴み、移動先の列へドラッグして放す */
    async function dragToColumn(page: Page, todo_id: string, status: 'open' | 'in_progress' | 'done'): Promise<void> {
        const handle = await page.getByTestId(`todo-board-handle-${todo_id}`).boundingBox();
        const column = await page.getByTestId(`todo-board-column-${status}`).boundingBox();
        expect(handle).not.toBeNull();
        expect(column).not.toBeNull();
        const start = { x: handle!.x + handle!.width / 2, y: handle!.y + handle!.height / 2 };
        await page.mouse.move(start.x, start.y);
        await page.mouse.down();
        await page.mouse.move(start.x + 12, start.y + 12, { steps: 4 });
        await page.mouse.move(column!.x + column!.width / 2, column!.y + column!.height / 2, { steps: 15 });
        await page.mouse.up();
    }

    test('admin がカードを別の列へ移すとステータスが変わる (デスクトップはマウスのドラッグ、モバイルはカードのメニュー)', async ({ openAs, isMobile }) => {
        const admin = await openAs('alpha-admin');
        const title = newTitle();
        const todo = await createTodo(admin.request, { title, visibility: 'tenant' });

        await admin.goto(boardPathOf(title));
        const card = admin.getByTestId(`todo-board-card-${todo.id}`);
        await expect(admin.getByTestId('todo-board-column-open').getByTestId(`todo-board-card-${todo.id}`)).toBeVisible();
        // 自分の ID を取得するまでカードは掴めない
        await expect(admin.getByTestId(`todo-board-handle-${todo.id}`)).toHaveAttribute('aria-disabled', 'false');

        // 未着手 -> 進行中
        if (isMobile) await moveViaMenu(admin, todo.id, 'in_progress');
        else await dragToColumn(admin, todo.id, 'in_progress');
        await expect(admin.getByTestId('todo-list-notice')).toContainText('ステータスを「進行中」に変更しました');
        await expect(admin.getByTestId('todo-board-column-in_progress').getByTestId(`todo-board-card-${todo.id}`)).toBeVisible();
        await expect(admin.getByTestId('todo-board-column-open').getByTestId(`todo-board-card-${todo.id}`)).toHaveCount(0);
        await expect(card).toHaveCount(1);
        expect((await fetchTodo(admin.request, todo.id)).status).toBe('in_progress');

        // 進行中 -> 完了 (どちらのプロジェクトもカードのメニュー)
        await moveViaMenu(admin, todo.id, 'done');
        await expect(admin.getByTestId('todo-list-notice')).toContainText('ステータスを「完了」に変更しました');
        await expect(admin.getByTestId('todo-board-column-done').getByTestId(`todo-board-card-${todo.id}`)).toBeVisible();
        expect((await fetchTodo(admin.request, todo.id)).status).toBe('done');
    });

    test('キーボード (ハンドルにフォーカス -> Space -> 右矢印 -> Space) でカードを未着手から進行中の列へ移せる', async ({ openAs, isMobile }) => {
        test.skip(isMobile, 'キーボード操作はデスクトップのプロジェクトで確認する (モバイルのカードのメニューでの変更は上のテストで確認する)');
        const admin = await openAs('alpha-admin');
        const title = newTitle();
        const todo = await createTodo(admin.request, { title, visibility: 'tenant' });

        await admin.goto(boardPathOf(title));
        const handle = admin.getByTestId(`todo-board-handle-${todo.id}`);
        await expect(handle).toHaveAttribute('aria-disabled', 'false');
        await handle.focus();
        // 各操作の効果を待ってから次のキーを押す (持ち上げの直後は、矢印のキーを受け取る準備がまだ整っていないことがある)
        await admin.keyboard.press('Space');
        await expect(handle).toHaveAttribute('aria-pressed', 'true');
        await admin.keyboard.press('ArrowRight');
        await expect(admin.getByTestId('todo-board-column-in_progress')).toHaveAttribute('data-over', 'true');
        await admin.keyboard.press('Space');

        await expect(admin.getByTestId('todo-list-notice')).toContainText('ステータスを「進行中」に変更しました');
        await expect(admin.getByTestId('todo-board-column-in_progress').getByTestId(`todo-board-card-${todo.id}`)).toBeVisible();
        expect((await fetchTodo(admin.request, todo.id)).status).toBe('in_progress');
    });

    test('作成者でも担当者でもない member は、カードを掴めず (aria-disabled)、メニューも出ない。担当しているカードは掴める', async ({ openAs, isMobile }) => {
        const admin = await openAs('alpha-admin');
        const viewer_title = newTitle();
        const assigned_title = newTitle();
        // 閲覧だけ: tenant 公開で担当者なし。比較用: 同じく tenant 公開で alpha-member が担当者
        const viewer_todo = await createTodo(admin.request, { title: viewer_title, visibility: 'tenant' });
        const assigned_todo = await createTodo(admin.request, { title: assigned_title, visibility: 'tenant', assignee_ids: [await memberIdOf(admin)] });

        // 担当しているカードが掴めることを確認して (= 自分の ID を取得済み)、画面を移らずに検索で閲覧だけのカードへ切り替える
        const member = await openAs('alpha-member');
        await member.goto(boardPathOf(assigned_title));
        await expect(member.getByTestId(`todo-board-handle-${assigned_todo.id}`)).toHaveAttribute('aria-disabled', 'false');
        await expect(member.getByTestId(`todo-board-menu-${assigned_todo.id}`)).toBeVisible();
        await member.getByTestId('todo-search-input').fill(viewer_title);
        await member.getByTestId('todo-search-input').press('Enter');

        const handle = member.getByTestId(`todo-board-handle-${viewer_todo.id}`);
        await expect(handle).toHaveAttribute('aria-disabled', 'true');
        await expect(handle).toHaveAttribute('data-locked', 'true');
        await expect(member.getByTestId(`todo-board-card-${viewer_todo.id}`)).toHaveAttribute('data-draggable', 'false');
        await expect(member.getByTestId(`todo-board-menu-${viewer_todo.id}`)).toHaveCount(0);
        await expect(member.getByTestId(`todo-board-card-${assigned_todo.id}`)).toHaveCount(0);

        // 掴もうとしても動かない (デスクトップのみ。マウスのドラッグとキーボード)
        if (!isMobile) {
            await dragToColumn(member, viewer_todo.id, 'in_progress');
            await handle.focus();
            await member.keyboard.press('Space');
            await member.keyboard.press('ArrowRight');
            await member.keyboard.press('Space');
            await expect(member.getByTestId('todo-board-column-open').getByTestId(`todo-board-card-${viewer_todo.id}`)).toBeVisible();
            await expect(member.getByTestId('todo-list-notice')).toHaveCount(0);
            expect((await fetchTodo(admin.request, viewer_todo.id)).status).toBe('open');
        }
    });
});

test.describe('AP: ToDo の同時編集', () => {
    test('別のタブで先に保存されて 412 になると、最新の内容を自動で再表示し、未保存の説明の入力は残る', async ({ openAs }) => {
        const tab_a = await openAs('alpha-admin');
        const tab_b = await openAs('alpha-admin');
        const title = newTitle();
        // 変更後のタイトルも E2E の命名 (`E2E ToDo <8 文字>`) にする。命名から外れるとティアダウンの後片付け (完全一致) の対象にならず残る
        const new_title = newTitle();
        const todo = await createTodo(tab_a.request, { title, visibility: 'tenant' });
        await openDetail(tab_a, todo.id, title);
        await openDetail(tab_b, todo.id, title);

        // タブ A: タイトルを保存する (ToDo のバージョンが上がる)
        await tab_a.getByTestId('todo-edit-title').fill(new_title);
        await tab_a.getByTestId('todo-fields-submit').click();
        await expect(tab_a.getByTestId('todo-detail-notice')).toContainText('変更を保存しました');

        // タブ B: 説明を未保存のまま、別のフォームのステータスを保存する -> 412 -> 自動で再表示
        await tab_b.getByTestId('todo-edit-description').fill('タブ B で入力中の説明 (未保存)');
        await tab_b.getByTestId('todo-status-in_progress').click();
        await expect(tab_b.getByTestId('todo-detail-refreshed')).toContainText('他のユーザーが更新したため最新の内容を表示しました');
        await expect(tab_b.getByTestId('todo-detail-title')).toHaveText(new_title);
        await expect(tab_b.getByTestId('todo-edit-title')).toHaveValue(new_title);
        await expect(tab_b.getByTestId('todo-edit-description')).toHaveValue('タブ B で入力中の説明 (未保存)');
        await expect(tab_b.getByTestId('todo-detail-action-error')).toHaveCount(0);
        await expect(tab_b.getByTestId('todo-detail-status-chip')).toHaveAttribute('data-status', 'open');

        // 最新の内容を確認してもう一度操作すれば保存でき、未保存の入力は残ったまま
        await tab_b.getByTestId('todo-status-in_progress').click();
        await expect(tab_b.getByTestId('todo-detail-status-chip')).toHaveAttribute('data-status', 'in_progress');
        await expect(tab_b.getByTestId('todo-edit-description')).toHaveValue('タブ B で入力中の説明 (未保存)');
        expect((await fetchTodo(tab_a.request, todo.id)).status).toBe('in_progress');
    });
});

test.describe('AP: ホームの ToDo の要約', () => {
    test('担当の ToDo の要約カードが表示され、カードのリンク先の一覧は絞り込みが URL に入っている', async ({ openAs }) => {
        const admin = await openAs('alpha-admin');
        const title = newTitle();
        const two_days_ago = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
        // 期限切れの担当 ToDo (alpha-member が担当)
        const todo = await createTodo(admin.request, { title, visibility: 'tenant', due_date: two_days_ago, assignee_ids: [await memberIdOf(admin)] });

        const member = await openAs('alpha-member');
        await member.goto(appPath(''));
        await expect(member.getByTestId('todo-summary')).toBeVisible();
        await expect(member.getByTestId('todo-summary-cards')).toBeVisible();
        for (const key of ['assigned_unfinished', 'assigned_overdue', 'assigned_due_soon', 'created_unfinished']) {
            await expect(member.getByTestId(`todo-summary-card-${key}`)).toBeVisible();
        }
        await expect(member.getByTestId('todo-summary-card-assigned_unfinished')).toHaveAttribute('data-count', /^[1-9]\d*$/);
        await expect(member.getByTestId('todo-summary-card-assigned_overdue')).toHaveAttribute('data-count', /^[1-9]\d*$/);

        // 期限切れのカード -> 担当・未完了・期限が昨日以前の一覧 (絞り込みは URL に入っている)
        await member.getByTestId('todo-summary-link-assigned_overdue').click();
        await expect(member).toHaveURL(/\/todos\?/);
        await expect(member).toHaveURL(/scope=assigned/);
        await expect(member).toHaveURL(/status=open/);
        await expect(member).toHaveURL(/due_before=\d{4}-\d{2}-\d{2}/);
        await expect(member).toHaveURL(/sort=due_date/);
        await expect(member.getByTestId('app-todo-list-page')).toHaveAttribute('data-scope', 'assigned');
        await expect(member.getByTestId('todo-filter-toggle')).toHaveAccessibleName(/件の条件を適用中/);
        // 期限切れの担当 ToDo が一覧に出る (他の実行の ToDo と混ざるため、タイトルで絞り込んで確認する)
        await member.getByTestId('todo-search-input').fill(title);
        await member.getByTestId('todo-search-input').press('Enter');
        await expect(member).toHaveURL(/q=E2E/);
        await expect(listItemOf(member, todo.id)).toContainText(title);
    });
});

test.describe('AP: ToDo のコメント・チェックリストのテナント分離', () => {
    test('別テナントの beta-member は、alpha の ToDo のコメント・チェックリストを取得も変更もできない (404)', async ({ openAs }) => {
        const admin = await openAs('alpha-admin');
        const title = newTitle();
        // 存在しないための 404 ではないことを示すため、コメントとチェック項目がある tenant 公開の ToDo を用意する
        const todo = await createTodo(admin.request, { title, visibility: 'tenant' });
        const comment = await createComment(admin.request, todo.id, 'alpha だけが読めるコメント');
        const item = await createChecklistItem(admin.request, todo.id, 'alpha だけが読める項目');
        expect((await admin.request.get(`/api/v1/todos/${todo.id}/comments`)).status()).toBe(200);
        expect((await admin.request.get(`/api/v1/todos/${todo.id}/checklist`)).status()).toBe(200);

        // beta-member (ページの request コンテキスト = beta のセッション Cookie)
        const beta = await openAs('beta-member');
        const base = `/api/v1/todos/${todo.id}`;
        for (const path of [`${base}`, `${base}/comments`, `${base}/checklist`]) {
            const response = await beta.request.get(path);
            expect(response.status(), `GET ${path}`).toBe(404);
            expect(await response.text()).not.toContain('alpha だけが読める');
        }
        const created_comment = await beta.request.post(`${base}/comments`, { data: { body: 'beta からのコメント' }, headers: CSRF_HEADERS });
        expect(created_comment.status(), 'POST comments').toBe(404);
        const created_item = await beta.request.post(`${base}/checklist/items`, { data: { title: 'beta からの項目' }, headers: CSRF_HEADERS });
        expect(created_item.status(), 'POST checklist/items').toBe(404);
        const deleted = await beta.request.delete(`${base}/comments/${comment.id}`, { headers: { ...CSRF_HEADERS, 'If-Match': '"1"' } });
        expect(deleted.status(), 'DELETE comments').toBe(404);
        const checked = await beta.request.patch(`${base}/checklist/items/${item.id}`, { data: { is_done: true }, headers: { ...CSRF_HEADERS, 'If-Match': '"1"' } });
        expect(checked.status(), 'PATCH checklist/items').toBe(404);

        // alpha 側は何も変わっていない
        const comments = (await (await admin.request.get(`${base}/comments`)).json()) as { items: { body: string }[] };
        expect(comments.items.map((entry) => entry.body)).toEqual(['alpha だけが読めるコメント']);
        const checklist = (await (await admin.request.get(`${base}/checklist`)).json()) as { items: { title: string; is_done: boolean }[] };
        expect(checklist.items.map((entry) => [entry.title, entry.is_done])).toEqual([['alpha だけが読める項目', false]]);
        expect(TENANT_CODE).toBe('alpha');
    });
});
