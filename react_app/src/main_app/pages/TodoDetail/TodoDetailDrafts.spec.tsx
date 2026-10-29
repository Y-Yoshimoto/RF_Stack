// ToDo 詳細画面のテスト: 同時編集 (412) での自動の再表示と未保存の入力の保持 (AP-UX-07・AP-UX-08)、見出しの下の作成者・更新者、区画の並び
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { TodoDetail } from '@/main_app/api/contract';
import { OTHER_USER_ID } from '@/main_app/testing/app_test_support';
import { THIRD_USER_ID } from '@/main_app/testing/story_data';
import { DETAIL_KEY, PATCH_KEY, detailReply, renderTodoDetail } from '@/main_app/testing/todo_detail_support';
import { TODO_ID, assigneeOf, todoUserRefOf } from '@/main_app/testing/todo_test_data';
import { calledKeys, calledRequests, problemReply, type MockReply, type mockFetch as MockFetch } from '@/shared/testing/fetch_mock';

afterEach(() => {
    vi.restoreAllMocks();
});

const updated = (overrides: Partial<TodoDetail>): MockReply => detailReply({ version: 4, ...overrides });
const requestsOf = (spy: ReturnType<typeof MockFetch>, method: string) => calledRequests(spy).filter((request) => request.method === method);

/**
 * 項目のタイトルを入力し直す関数
 * @param {ReturnType<typeof userEvent.setup>} user ユーザー操作
 * @param {string} title タイトル
*/
const typeTitle = async (user: ReturnType<typeof userEvent.setup>, title: string) => {
    await user.clear(screen.getByTestId('todo-edit-title'));
    await user.type(screen.getByTestId('todo-edit-title'), title);
};

describe('ToDo 詳細画面: 同時編集 (412) の自動の再表示 (AP-UX-07)', () => {
    it('412 で失敗したら最新の内容を自動で再表示し、入力は残したまま、重なった項目を知らせる。もう一度保存すると新しい版で通る', async () => {
        const user = userEvent.setup();
        let detail_calls = 0;
        let patch_calls = 0;
        const spy = renderTodoDetail({
            replies: {
                [DETAIL_KEY]: () => {
                    detail_calls += 1;
                    return detail_calls === 1 ? detailReply() : detailReply({ version: 4, title: '他の人のタイトル', description: '他の人の説明' });
                },
                [PATCH_KEY]: () => {
                    patch_calls += 1;
                    return patch_calls === 1 ? problemReply(412, 'todo_version_conflict') : updated({ version: 5, title: 'x', description: '他の人の説明' });
                },
            },
        });
        await screen.findByTestId('todo-fields-form');
        await typeTitle(user, 'x');
        await user.click(screen.getByTestId('todo-fields-submit'));

        const notice = await screen.findByTestId('todo-detail-refreshed');
        expect(notice).toHaveAttribute('role', 'alert');
        expect(notice).toHaveTextContent('他のユーザーが更新したため最新の内容を表示しました。');
        expect(notice).toHaveTextContent('タイトルは他の人も変更しています。');
        expect(notice).toHaveTextContent('確認してもう一度保存してください');
        // 失敗の通知は出さず、入力は残り、触っていない項目は最新になる
        expect(screen.queryByTestId('todo-detail-action-error')).toBeNull();
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('x');
        expect(screen.getByTestId('todo-edit-description')).toHaveValue('他の人の説明');
        expect(screen.getByTestId('todo-fields-form')).toHaveAttribute('data-conflict', 'true');
        expect(calledKeys(spy).filter((key) => key === DETAIL_KEY)).toHaveLength(2);

        // 確認してもう一度保存すると、最新の ETag (4) で通る
        await user.click(screen.getByTestId('todo-fields-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('変更を保存しました');
        expect(requestsOf(spy, 'PATCH').at(-1)?.headers.get('If-Match')).toBe('"4"');
        expect(screen.queryByTestId('todo-detail-refreshed')).toBeNull();
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('x');
    });

    it('他の人が変えたのが別の項目なら、重なりは知らせない (入力は残る)', async () => {
        const user = userEvent.setup();
        let detail_calls = 0;
        renderTodoDetail({
            replies: {
                [DETAIL_KEY]: () => {
                    detail_calls += 1;
                    return detail_calls === 1 ? detailReply() : detailReply({ version: 4, description: '他の人の説明' });
                },
                [PATCH_KEY]: problemReply(412, 'todo_version_conflict'),
            },
        });
        await screen.findByTestId('todo-fields-form');
        await typeTitle(user, 'x');
        await user.click(screen.getByTestId('todo-fields-submit'));
        const notice = await screen.findByTestId('todo-detail-refreshed');
        expect(notice).not.toHaveTextContent('他の人も変更しています');
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('x');
        expect(screen.getByTestId('todo-fields-form')).toHaveAttribute('data-conflict', 'false');
    });

    it('担当者の保存が 412 でも自動で再表示し、担当者の入力が他の人の変更と重なれば知らせる', async () => {
        const user = userEvent.setup();
        let detail_calls = 0;
        renderTodoDetail({
            replies: {
                [DETAIL_KEY]: () => {
                    detail_calls += 1;
                    // 他の人が担当者を追加した
                    return detail_calls === 1 ? detailReply() : detailReply({ version: 4, assignees: [assigneeOf(), assigneeOf({ user_id: THIRD_USER_ID, display_name: 'Jiro Suzuki' })] });
                },
                [`PUT /api/v1/todos/${TODO_ID}/assignees`]: problemReply(412, 'todo_version_conflict'),
            },
        });
        await screen.findByTestId('todo-assignees-form');
        await user.click(within(screen.getByTestId(`todo-edit-assignees-chip-${OTHER_USER_ID}`)).getByTestId('CancelIcon'));
        await user.click(screen.getByTestId('todo-assignees-submit'));
        const notice = await screen.findByTestId('todo-detail-refreshed');
        expect(notice).toHaveTextContent('担当者は他の人も変更しています。');
        // 入力 (全員外す) は残る
        expect(screen.queryByTestId(`todo-edit-assignees-chip-${OTHER_USER_ID}`)).toBeNull();
        expect(screen.getByTestId('todo-assignees-form')).toHaveAttribute('data-conflict', 'true');
    });

    it('再表示にも失敗したら、従来どおり再読み込みを促す', async () => {
        const user = userEvent.setup();
        let detail_calls = 0;
        renderTodoDetail({
            replies: {
                [DETAIL_KEY]: () => {
                    detail_calls += 1;
                    return detail_calls === 1 ? detailReply() : problemReply(404, 'todo_not_found');
                },
                [PATCH_KEY]: problemReply(412, 'todo_version_conflict'),
            },
        });
        await screen.findByTestId('todo-fields-form');
        await typeTitle(user, 'x');
        await user.click(screen.getByTestId('todo-fields-submit'));
        expect(await screen.findByTestId('todo-detail-action-error')).toHaveAttribute('data-error-code', 'todo_version_conflict');
        expect(screen.queryByTestId('todo-detail-refreshed')).toBeNull();
        // 表示は前のまま、入力も残る
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('x');
    });
});

describe('ToDo 詳細画面: 1 つのフォームを保存しても他のフォームの入力は残る (AP-UX-08)', () => {
    it('項目を保存しても、未保存の担当者の入力は消えず、項目のフォームはきれいな状態に戻る', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail({ replies: { [PATCH_KEY]: updated({ title: '新しいタイトル' }) } });
        await screen.findByTestId('todo-assignees-form');
        await user.click(within(screen.getByTestId(`todo-edit-assignees-chip-${OTHER_USER_ID}`)).getByTestId('CancelIcon'));
        expect(screen.getByTestId('todo-assignees-submit')).toBeEnabled();

        await typeTitle(user, '新しいタイトル');
        await user.click(screen.getByTestId('todo-fields-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('変更を保存しました');
        expect(requestsOf(spy, 'PATCH')).toHaveLength(1);

        // 担当者の入力は残り (外したまま・保存できる)、項目はきれい (保存できない)
        expect(screen.queryByTestId(`todo-edit-assignees-chip-${OTHER_USER_ID}`)).toBeNull();
        expect(screen.getByTestId('todo-assignees-submit')).toBeEnabled();
        expect(screen.getByTestId('todo-fields-submit')).toBeDisabled();
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('新しいタイトル');
    });

    it('閲覧範囲を保存しても、未保存の項目の入力 (タイトル) は消えない', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ replies: { [PATCH_KEY]: updated({ visibility: 'tenant', effective_visibility: 'tenant', organizations: [] }) } });
        await screen.findByTestId('todo-audience-form');
        await typeTitle(user, '書きかけ');
        await user.click(screen.getByTestId('todo-edit-audience-visibility-tenant'));
        await user.click(screen.getByTestId('todo-audience-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('閲覧範囲を保存しました');
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('書きかけ');
        expect(screen.getByTestId('todo-fields-submit')).toBeEnabled();
        expect(screen.getByTestId('todo-audience-submit')).toBeDisabled();
    });

    it('前後に空白のあるタイトルを保存すると、保存した値 (空白なし) できれいな状態に戻る', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ replies: { [PATCH_KEY]: updated({ title: 'x' }) } });
        await screen.findByTestId('todo-fields-form');
        await typeTitle(user, '  x  ');
        await user.click(screen.getByTestId('todo-fields-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toBeInTheDocument();
        expect(screen.getByTestId('todo-edit-title')).toHaveValue('x');
        expect(screen.getByTestId('todo-fields-submit')).toBeDisabled();
    });
});

describe('ToDo 詳細画面: 見出しの下の作成者・更新者 (AP-UX-09) と区画の並び', () => {
    it('作成者・作成日時と最終更新者・更新日時を出し、無効なユーザーには「(無効)」を添える', async () => {
        renderTodoDetail({ detail: { updater: { ...todoUserRefOf(OTHER_USER_ID, 'Taro Yamada'), is_active: false }, updated_at: '2026-10-05T03:00:00Z' } });
        const meta = await screen.findByTestId('todo-detail-meta');
        expect(within(meta).getByTestId('todo-detail-created')).toHaveTextContent('作成: Hanako Suzuki・2026/10/01 9:00');
        expect(within(meta).getByTestId('todo-detail-updated')).toHaveTextContent('最終更新: Taro Yamada (無効)・2026/10/05 12:00');
    });

    it('区画は「ステータス → 項目 → チェックリスト → 担当者 → 閲覧範囲 → コメント / アクティビティ」の順', async () => {
        renderTodoDetail();
        await screen.findByTestId('todo-fields-form');
        const ids = ['todo-status-section', 'todo-fields-section', 'todo-checklist-section', 'todo-assignees-section', 'todo-audience-section', 'todo-collab-section'];
        const elements = ids.map((id) => screen.getByTestId(id));
        elements.slice(1).forEach((element, index) => {
            expect(elements[index].compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        });
        expect(screen.getByTestId('todo-tab-comments')).toHaveTextContent('コメント (0)');
    });
});
