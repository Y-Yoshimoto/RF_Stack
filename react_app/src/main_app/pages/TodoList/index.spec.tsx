// ToDo 一覧画面のテスト (表・表示範囲のタブ・URL クエリの絞り込み・一覧からのステータス変更の出し分け・412 の再読み込み・さらに読み込む・空・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { OTHER_USER_ID, SELF_USER_ID, organizationOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_USERS, THIRD_USER_ID, meBodyOf, pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, todoDetailOf, todoOf } from '@/main_app/testing/todo_test_data';
import { AppTodoListPage } from '.';

const LIST_KEY = 'GET /api/v1/todos';
const SECOND_TODO_ID = '01900000-0000-7000-8000-00000000c002';
const THIRD_TODO_ID = '01900000-0000-7000-8000-00000000c003';

afterEach(() => {
    vi.restoreAllMocks();
});

/** 自分が作成した ToDo、他人が作成し自分が担当でない ToDo (member は状態を変えられない) */
const MINE = todoOf({ title: '自分の ToDo', created_by: SELF_USER_ID, assignees: [] });
const OTHERS = todoOf({ id: SECOND_TODO_ID, title: '他人の ToDo', created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: THIRD_USER_ID, display_name: 'Jiro Suzuki', is_active: false })], visibility: 'tenant', effective_visibility: 'tenant', organizations: [], priority: 'high', due_date: null });

/**
 * 一覧画面を描画する関数
 * @param {MockHandler} reply 一覧 API の応答
 * @param {{ path?: string; roles?: string[]; replies?: Record<string, MockHandler> }} options 最初のパス・ロール・追加の応答
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderList = (reply: MockHandler, { path = '/alpha/todos', roles = ['tenant_admin'], replies = {} }: { path?: string; roles?: string[]; replies?: Record<string, MockHandler> } = {}) => {
    const spy = mockFetch({
        [LIST_KEY]: reply,
        'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles) },
        'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) },
        'GET /api/v1/organizations': { status: 200, body: pageOf([organizationOf()]) },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/todos" element={<AppTodoListPage />} />, { path, roles });
    return spy;
};

const PAGE = { status: 200, body: pageOf([MINE, OTHERS]) };

describe('ToDo 一覧画面', () => {
    it('表に、タイトル・ステータス・優先度・期限・担当者・公開範囲を表示し、見出しを th にする', async () => {
        renderList(PAGE);
        const table = await screen.findByTestId('todo-table');
        expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['タイトル', 'ステータス', '優先度', '期限', '担当者', '公開範囲']);
        expect(screen.getByTestId(`todo-link-${MINE.id}`)).toHaveAttribute('href', `/alpha/todos/${MINE.id}`);
        expect(screen.getByTestId(`todo-due-${MINE.id}`)).toHaveTextContent('2026-11-01');
        expect(screen.getByTestId(`todo-due-${SECOND_TODO_ID}`)).toHaveTextContent('期限なし');
        expect(screen.getByTestId(`todo-priority-${SECOND_TODO_ID}`)).toHaveTextContent('優先度 高');
        expect(screen.getByTestId(`todo-assignees-${SECOND_TODO_ID}`)).toHaveTextContent('Jiro Suzuki (無効)');
        expect(screen.getByTestId(`todo-assignees-${MINE.id}`)).toHaveTextContent('未割り当て');
        expect(screen.getByTestId(`todo-audience-${MINE.id}`)).toHaveTextContent('組織: 営業部');
        expect(screen.getByTestId(`todo-audience-${SECOND_TODO_ID}`)).toHaveTextContent('テナント全体');
        expect(screen.getByTestId('todo-list-count')).toHaveTextContent('2 件を表示');
    });

    it('公開先の組織がすべて削除された ToDo は、非公開扱いと再指定が必要なことを示す', async () => {
        renderList({ status: 200, body: pageOf([todoOf({ visibility: 'organization', effective_visibility: 'private', organizations: [] })]) });
        expect(await screen.findByTestId(`todo-reselect-${MINE.id}`)).toHaveTextContent('公開先の再指定が必要');
    });

    it('ステータスは色だけでなく、文字で示す', async () => {
        renderList({ status: 200, body: pageOf([todoOf({ status: 'done', created_by: OTHER_USER_ID, assignees: [] })]) }, { roles: ['member'] });
        expect(await screen.findByTestId(`todo-status-chip-${MINE.id}`)).toHaveTextContent('完了');
    });

    it('表示範囲のタブを URL (scope) と API に反映する', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE);
        await screen.findByTestId('todo-table');
        expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['すべて', '自分が作成', '自分が担当', '共有された']);
        await user.click(screen.getByTestId('todo-scope-assigned'));
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('scope') === 'assigned')).toBe(true));
        expect(screen.getByTestId('todo-scope-assigned')).toHaveAttribute('aria-selected', 'true');
    });

    it('URL のクエリを絞り込みに使い、入力欄にも反映する', async () => {
        const spy = renderList(PAGE, { path: '/alpha/todos?scope=mine&status=open,in_progress&priority=high&q=見積&due_before=2026-12-31&sort=due_date' });
        await screen.findByTestId('todo-table');
        const params = new URL(calledRequests(spy).find((request) => request.url.includes('/todos'))?.url ?? '').searchParams;
        expect(Object.fromEntries(params)).toMatchObject({ scope: 'mine', status: 'open,in_progress', priority: 'high', q: '見積', due_before: '2026-12-31', sort: 'due_date' });
        expect(screen.getByTestId('todo-filter-status-open')).toHaveAttribute('aria-pressed', 'true');
        expect(screen.getByTestId('todo-filter-status-done')).toHaveAttribute('aria-pressed', 'false');
        expect(screen.getByTestId('todo-search-input')).toHaveValue('見積');
        expect(screen.getByTestId('todo-filter-due-before')).toHaveValue('2026-12-31');
    });

    it('ステータスの絞り込みを切り替えると、API に渡して取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE);
        await screen.findByTestId('todo-table');
        await user.click(screen.getByTestId('todo-filter-status-done'));
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('status') === 'done')).toBe(true));
        expect(screen.getByTestId('todo-filter-clear')).toBeInTheDocument();
    });

    it('検索はタイトルの部分一致として q を送る', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE);
        await screen.findByTestId('todo-table');
        await user.type(screen.getByTestId('todo-search-input'), '見積{Enter}');
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('q') === '見積')).toBe(true));
    });

    it('並び替えは、キーを 1 つ選んで sort に渡す', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE);
        await screen.findByTestId('todo-table');
        await user.click(screen.getByRole('combobox', { name: '並び替え' }));
        await user.click(screen.getByRole('option', { name: '優先度が高い順' }));
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('sort') === '-priority')).toBe(true));
    });

    it('tenant_admin には、すべての行にステータスの変更を出す', async () => {
        renderList(PAGE);
        await screen.findByTestId('todo-table');
        expect(screen.getByTestId(`todo-status-select-${MINE.id}`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-status-select-${SECOND_TODO_ID}`)).toBeInTheDocument();
    });

    it('member には、自分が作成または担当の行だけにステータスの変更を出し、他の行はチップで表示する', async () => {
        const assigned = todoOf({ id: THIRD_TODO_ID, title: '担当している ToDo', created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: SELF_USER_ID })] });
        renderList({ status: 200, body: pageOf([MINE, OTHERS, assigned]) }, { roles: ['member'] });
        await screen.findByTestId('todo-table');
        expect(screen.getByTestId(`todo-status-select-${MINE.id}`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-status-select-${THIRD_TODO_ID}`)).toBeInTheDocument();
        expect(screen.queryByTestId(`todo-status-select-${SECOND_TODO_ID}`)).toBeNull();
        expect(screen.getByTestId(`todo-status-chip-${SECOND_TODO_ID}`)).toHaveTextContent('未着手');
    });

    it('一覧からステータスを変えると、version を If-Match に付けて status だけを送り、行を更新して知らせる', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE, {
            replies: { [`PATCH /api/v1/todos/${MINE.id}`]: { status: 200, body: todoDetailOf({ ...MINE, status: 'in_progress', version: 4 }), headers: { ETag: '"4"' } } },
        });
        await screen.findByTestId('todo-table');
        await user.click(within(screen.getByTestId(`todo-status-select-${MINE.id}`)).getByRole('combobox'));
        await user.click(screen.getByTestId(`todo-status-option-${MINE.id}-in_progress`));
        expect(await screen.findByTestId('todo-list-notice')).toHaveTextContent('「自分の ToDo」のステータスを「進行中」に変更しました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ status: 'in_progress' });
        expect(screen.getByTestId(`todo-status-select-${MINE.id}`)).toHaveTextContent('進行中');
    });

    it('一覧からの変更が 412 で失敗すると、role="alert" で再読み込みを促し、再読み込みで一覧を取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE, { replies: { [`PATCH /api/v1/todos/${MINE.id}`]: problemReply(412, 'todo_version_conflict') } });
        await screen.findByTestId('todo-table');
        await user.click(within(screen.getByTestId(`todo-status-select-${MINE.id}`)).getByRole('combobox'));
        await user.click(screen.getByTestId(`todo-status-option-${MINE.id}-done`));
        const alert = await screen.findByTestId('todo-list-action-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('他の操作で更新されています');
        const before = calledRequests(spy).filter((request) => request.method === 'GET' && request.url.includes('/todos')).length;
        await user.click(screen.getByTestId('todo-list-action-error-reload'));
        await vi.waitFor(() => expect(calledRequests(spy).filter((request) => request.method === 'GET' && request.url.includes('/todos')).length).toBeGreaterThan(before));
        await vi.waitFor(() => expect(screen.queryByTestId('todo-list-action-error')).toBeNull());
    });

    it('「さらに読み込む」で続きのページを連結する', async () => {
        const user = userEvent.setup();
        const spy = renderList((request) => {
            const cursor = new URL(request.url).searchParams.get('cursor');
            return cursor === null ? { status: 200, body: pageOf([MINE], 'next-1') } : { status: 200, body: pageOf([OTHERS], null) };
        });
        await screen.findByTestId('todo-table');
        expect(screen.getByTestId('todo-list-count')).toHaveTextContent('1 件を表示 (続きがあります)');
        await user.click(screen.getByTestId('todo-list-load-more'));
        await vi.waitFor(() => expect(screen.getByTestId('todo-list-count')).toHaveTextContent('2 件を表示'));
        expect(new URL(calledRequests(spy).filter((request) => request.url.includes('/todos'))[1].url).searchParams.get('cursor')).toBe('next-1');
    });

    it('ToDo がなければ、空の案内を表示する。絞り込み中は条件のクリアを案内する', async () => {
        renderList({ status: 200, body: pageOf([]) });
        expect(await screen.findByTestId('todo-list-empty')).toHaveTextContent('ToDo がありません');
        expect(screen.queryByTestId('todo-list-empty-clear')).toBeNull();
    });

    it('絞り込み中の空は「条件に合う ToDo がありません」と表示し、クリアで条件を外す', async () => {
        const user = userEvent.setup();
        renderList({ status: 200, body: pageOf([]) }, { path: '/alpha/todos?status=done' });
        expect(await screen.findByTestId('todo-list-empty')).toHaveTextContent('条件に合う ToDo がありません');
        await user.click(screen.getByTestId('todo-list-empty-clear'));
        await vi.waitFor(() => expect(screen.getByTestId('todo-filter-status-done')).toHaveAttribute('aria-pressed', 'false'));
    });

    it('取得に失敗すると、role="alert" のエラーと再試行を表示する', async () => {
        const user = userEvent.setup();
        let calls = 0;
        renderList(() => {
            calls += 1;
            return calls === 1 ? problemReply(500, 'internal_error') : PAGE;
        });
        const alert = await screen.findByTestId('todo-list-error');
        expect(alert).toHaveAttribute('role', 'alert');
        await user.click(screen.getByTestId('todo-list-error-reload'));
        expect(await screen.findByTestId('todo-table')).toBeInTheDocument();
    });

    it('作成の導線を出す (member にも)', async () => {
        renderList(PAGE, { roles: ['member'] });
        expect(await screen.findByTestId('todo-list-create')).toHaveAttribute('href', '/alpha/todos/new');
    });
});
