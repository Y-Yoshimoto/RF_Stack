// ToDo 一覧画面のテスト (表・表示範囲のタブ・URL クエリの絞り込み・折りたたみ式の絞り込みと適用中の条件・リスト／ボードの切り替え・一覧からのステータス変更の出し分け・
// 412 の再読み込み・無限スクロールと総件数・md 未満のカード表示・表示範囲ごとの空の案内・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page } from 'vitest/browser';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { pageOverflowOf, useMobileViewport } from '@/shared/testing/page_overflow';
import { OTHER_USER_ID, SELF_USER_ID, organizationOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_USERS, THIRD_USER_ID, meBodyOf, pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, todoDetailOf, todoOf } from '@/main_app/testing/todo_test_data';
import { AppTodoListPage } from '.';

const LIST_KEY = 'GET /api/v1/todos';
const SECOND_TODO_ID = '01900000-0000-7000-8000-00000000c002';
const THIRD_TODO_ID = '01900000-0000-7000-8000-00000000c003';

afterEach(async () => {
    vi.restoreAllMocks();
    // md 未満の幅で確かめたテストの後は、既定の幅 (vitest.config.js の browser.viewport) に戻す
    await page.viewport(1280, 720);
});

/** 絞り込みを開く (Collapse の中の入力は、開くまで操作できない) */
const openFilter = async (user: UserEvent) => {
    await user.click(screen.getByTestId('todo-filter-toggle'));
};

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
    it('表に、タイトル・ステータス・優先度・期限・担当者・公開範囲・作成者・更新日時を表示し、見出しを th にする', async () => {
        renderList(PAGE);
        const table = await screen.findByTestId('todo-table');
        expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['タイトル', 'ステータス', '優先度', '期限', '担当者', '公開範囲', '作成者', '更新日時']);
        expect(screen.getByTestId(`todo-link-${MINE.id}`)).toHaveAttribute('href', `/alpha/todos/${MINE.id}`);
        expect(screen.getByTestId(`todo-due-${MINE.id}`)).toHaveTextContent('2026-11-01');
        expect(screen.getByTestId(`todo-due-${SECOND_TODO_ID}`)).toHaveTextContent('期限なし');
        expect(screen.getByTestId(`todo-priority-${SECOND_TODO_ID}`)).toHaveTextContent('優先度 高');
        expect(screen.getByTestId(`todo-assignees-${SECOND_TODO_ID}`)).toHaveTextContent('Jiro Suzuki (無効)');
        expect(screen.getByTestId(`todo-assignees-${MINE.id}`)).toHaveTextContent('未割り当て');
        expect(screen.getByTestId(`todo-audience-${MINE.id}`)).toHaveTextContent('組織: 営業部');
        expect(screen.getByTestId(`todo-audience-${SECOND_TODO_ID}`)).toHaveTextContent('テナント全体');
        expect(screen.getByTestId(`todo-creator-${MINE.id}`)).toHaveTextContent('Hanako Suzuki');
        expect(screen.getByTestId(`todo-updated-${MINE.id}`)).toHaveTextContent('2026/10/01');
        expect(screen.getByTestId('todo-list-count')).toHaveTextContent('2 件を表示');
    });

    it('タイトルの下に、チェックリストの進捗 (3/5 と進捗バー) とコメント数を出す。0 件・コメントなしなら出さない', async () => {
        const with_progress = todoOf({ checklist: { done_count: 3, total_count: 5 }, comment_count: 4 });
        renderList({ status: 200, body: pageOf([with_progress, OTHERS]) });
        await screen.findByTestId('todo-table');
        const progress = screen.getByTestId(`todo-progress-${MINE.id}`);
        expect(progress).toHaveTextContent('3/5');
        expect(within(progress).getByRole('progressbar', { name: 'チェックリストの進捗 60%' })).toHaveAttribute('aria-valuenow', '60');
        expect(screen.getByTestId(`todo-comments-${MINE.id}`)).toHaveTextContent('4');
        expect(screen.queryByTestId(`todo-progress-${SECOND_TODO_ID}`)).toBeNull();
        expect(screen.queryByTestId(`todo-comments-${SECOND_TODO_ID}`)).toBeNull();
    });

    it('総件数が分かるときは「N 件中 M 件を表示」とする', async () => {
        renderList({ status: 200, body: { ...pageOf([MINE, OTHERS]), total: 120 } });
        await screen.findByTestId('todo-table');
        expect(screen.getByTestId('todo-list-count')).toHaveTextContent('120 件中 2 件を表示');
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
        await openFilter(user);
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
        await openFilter(user);
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

    it('末尾が見えたら続きのページを自動で読み込んで連結する (無限スクロール)', async () => {
        const spy = renderList((request) => {
            const cursor = new URL(request.url).searchParams.get('cursor');
            return cursor === null ? { status: 200, body: { ...pageOf([MINE], 'next-1'), total: 2 } } : { status: 200, body: pageOf([OTHERS], null) };
        });
        await screen.findByTestId('todo-table');
        await vi.waitFor(() => expect(screen.getByTestId('todo-list-count')).toHaveTextContent('2 件中 2 件を表示'));
        expect(screen.getByTestId(`todo-row-${SECOND_TODO_ID}`)).toBeInTheDocument();
        expect(screen.queryByTestId('todo-list-load-more')).toBeNull();
        const todo_requests = calledRequests(spy).filter((request) => request.url.includes('/todos'));
        expect(new URL(todo_requests[0].url).searchParams.get('cursor')).toBeNull();
        expect(new URL(todo_requests[1].url).searchParams.get('cursor')).toBe('next-1');
    });

    it('続きの読み込みに失敗したら自動での読み込みを止め、「さらに読み込む」と再試行を残す', async () => {
        const user = userEvent.setup();
        let second_calls = 0;
        renderList((request) => {
            const cursor = new URL(request.url).searchParams.get('cursor');
            if (cursor === null) return { status: 200, body: pageOf([MINE], 'next-1') };
            second_calls += 1;
            return second_calls === 1 ? problemReply(500, 'internal_error') : { status: 200, body: pageOf([OTHERS], null) };
        });
        expect(await screen.findByTestId('todo-list-load-more-error')).toHaveAttribute('role', 'alert');
        expect(second_calls).toBe(1);
        await user.click(screen.getByTestId('todo-list-load-more'));
        await vi.waitFor(() => expect(screen.getByTestId('todo-list-count')).toHaveTextContent('2 件を表示'));
        expect(screen.queryByTestId('todo-list-load-more-error')).toBeNull();
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

describe('ToDo 一覧画面: 絞り込みの折りたたみと適用中の条件', () => {
    it('検索欄と「絞り込み」ボタンだけを常に出し、残りは畳んでおく。ボタンで開閉する', async () => {
        const user = userEvent.setup();
        renderList(PAGE);
        await screen.findByTestId('todo-table');
        const toggle = screen.getByTestId('todo-filter-toggle');
        expect(screen.getByTestId('todo-search-input')).toBeVisible();
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(screen.getByTestId('todo-filter-status-open')).not.toBeVisible();
        await user.click(toggle);
        expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await vi.waitFor(() => expect(screen.getByTestId('todo-filter-status-open')).toBeVisible());
        expect(toggle).toHaveAttribute('aria-controls', screen.getByTestId('todo-filter-panel').id);
        await user.click(toggle);
        await vi.waitFor(() => expect(screen.getByTestId('todo-filter-status-open')).not.toBeVisible());
    });

    it('適用中の条件を、ボタンのバッジ (検索語を除く数) とチップで出す。条件が無ければ出さない', async () => {
        renderList(PAGE, { path: '/alpha/todos?status=open,in_progress&priority=high&q=見積&assignee_id=01900000-0000-7000-8000-00000000a002&due_before=2026-12-31' });
        await screen.findByTestId('todo-table');
        expect(within(screen.getByTestId('todo-active-filters')).getAllByRole('button').map((chip) => chip.textContent).filter((text) => text !== '絞り込みをクリア')).toEqual([
            'タイトル: 「見積」',
            'ステータス: 未着手',
            'ステータス: 進行中',
            '優先度: 高',
            '担当者: Taro Yamada',
            '期限: 2026-12-31 以前',
        ]);
        expect(screen.getByTestId('todo-filter-badge')).toHaveTextContent('5');
        expect(screen.getByTestId('todo-filter-toggle')).toHaveAccessibleName('絞り込み (5 件の条件を適用中)');
    });

    it('条件が無いときは、チップもバッジも出さない', async () => {
        renderList(PAGE);
        await screen.findByTestId('todo-table');
        expect(screen.queryByTestId('todo-active-filters')).toBeNull();
        expect(screen.getByTestId('todo-filter-toggle')).toHaveAccessibleName('絞り込み');
    });

    it('チップを押すと、その条件だけを外して取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE, { path: '/alpha/todos?status=open,done&priority=high&q=見積' });
        await screen.findByTestId('todo-table');
        await user.click(screen.getByTestId('todo-chip-status-open'));
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('status') === 'done')).toBe(true));
        expect(screen.queryByTestId('todo-chip-status-open')).toBeNull();
        expect(screen.getByTestId('todo-chip-status-done')).toBeInTheDocument();
        await user.click(screen.getByTestId('todo-chip-q'));
        await vi.waitFor(() => expect(screen.getByTestId('todo-search-input')).toHaveValue(''));
        expect(screen.getByTestId('todo-chip-priority-high')).toBeInTheDocument();
    });

    it('「絞り込みをクリア」で、検索語を含むすべての条件を外す。表示範囲は残す', async () => {
        const user = userEvent.setup();
        renderList(PAGE, { path: '/alpha/todos?scope=mine&status=done&q=見積' });
        await screen.findByTestId('todo-table');
        await user.click(screen.getByTestId('todo-filter-clear'));
        await vi.waitFor(() => expect(screen.queryByTestId('todo-active-filters')).toBeNull());
        expect(screen.getByTestId('todo-scope-mine')).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByTestId('todo-search-input')).toHaveValue('');
    });
});

describe('ToDo 一覧画面: リスト／ボードの切り替え', () => {
    /** ステータスの絞り込み (列) ごとに ToDo を返す応答 */
    const boardReply = (request: Request) => {
        const status = new URL(request.url).searchParams.get('status');
        const items = [MINE, OTHERS].filter((todo) => todo.status === status);
        return { status: 200, body: { ...pageOf(items), total: items.length } };
    };

    it('「リスト／ボード」の切り替えで URL の view を変える。ボードでは 3 列を、列ごとのステータスの絞り込みで取得する', async () => {
        const user = userEvent.setup();
        const spy = renderList(boardReply, { path: '/alpha/todos?status=open&priority=high' });
        await screen.findByTestId('todo-table');
        expect(screen.getByTestId('todo-view-list')).toHaveAttribute('aria-pressed', 'true');
        await user.click(screen.getByTestId('todo-view-board'));
        expect(await screen.findByTestId('todo-board')).toBeInTheDocument();
        expect(screen.getByTestId('app-todo-list-page')).toHaveAttribute('data-view', 'board');
        expect(screen.queryByTestId('todo-table')).toBeNull();
        expect(screen.getByTestId('todo-view-board')).toHaveAttribute('aria-pressed', 'true');
        await vi.waitFor(() => expect(screen.getByTestId('todo-board-count-done')).toBeInTheDocument());
        const column_params = calledRequests(spy).map((request) => new URL(request.url).searchParams).filter((params) => params.get('priority') === 'high');
        expect(new Set(column_params.map((params) => params.get('status')))).toEqual(new Set(['open', 'in_progress', 'done']));
        expect(column_params.every((params) => params.get('include_total') === 'true')).toBe(true);
        await user.click(screen.getByTestId('todo-view-list'));
        expect(await screen.findByTestId('todo-table')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-board')).toBeNull();
        // ボードに切り替えても URL のステータスの絞り込みは消えず、リストに戻すと効く
        expect(screen.getByTestId('todo-chip-status-open')).toBeInTheDocument();
    });

    it('ボード表示ではステータスの絞り込みを隠し、ステータスのチップとバッジの数にも含めない', async () => {
        const user = userEvent.setup();
        renderList(boardReply, { path: '/alpha/todos?view=board&status=done&priority=high' });
        await screen.findByTestId('todo-board');
        await openFilter(user);
        await vi.waitFor(() => expect(screen.getByTestId('todo-filter-priority')).toBeVisible());
        expect(screen.queryByTestId('todo-filter-status')).toBeNull();
        expect(screen.queryByTestId('todo-chip-status-done')).toBeNull();
        expect(screen.getByTestId('todo-chip-priority-high')).toBeInTheDocument();
        expect(screen.getByTestId('todo-filter-badge')).toHaveTextContent('1');
    });

    it('ボードのときだけ、ボード用の取得をする (リストの一覧は取得しない)', async () => {
        const spy = renderList(boardReply, { path: '/alpha/todos?view=board' });
        await screen.findByTestId('todo-board');
        await vi.waitFor(() => expect(screen.getByTestId('todo-board-count-open')).toBeInTheDocument());
        const without_status = calledRequests(spy).filter((request) => request.url.includes('/todos') && new URL(request.url).searchParams.get('status') === null);
        expect(without_status).toHaveLength(0);
    });
});

describe('ToDo 一覧画面: 空の案内', () => {
    it.each([
        ['all', '/alpha/todos', 'ToDo がありません。'],
        ['mine', '/alpha/todos?scope=mine', '自分が作成した ToDo はありません。'],
        ['assigned', '/alpha/todos?scope=assigned', '自分が担当の ToDo はありません。'],
        ['shared', '/alpha/todos?scope=shared', '共有された ToDo はありません。'],
    ])('表示範囲 %s では、その範囲の案内と作成への導線を出す', async (scope, path, title) => {
        renderList({ status: 200, body: pageOf([]) }, { path });
        const empty = await screen.findByTestId('todo-list-empty');
        expect(empty).toHaveAttribute('data-scope', scope);
        expect(within(empty).getByRole('heading', { name: title })).toBeInTheDocument();
        expect(within(empty).getByTestId('todo-list-empty-create')).toHaveAttribute('href', '/alpha/todos/new');
        expect(screen.queryByTestId('todo-list-empty-clear')).toBeNull();
    });

    it('絞り込み中は「絞り込みをクリア」を出し、作成への導線も残す', async () => {
        renderList({ status: 200, body: pageOf([]) }, { path: '/alpha/todos?scope=mine&priority=low' });
        const empty = await screen.findByTestId('todo-list-empty');
        expect(empty).toHaveTextContent('条件に合う ToDo がありません');
        expect(within(empty).getByTestId('todo-list-empty-clear')).toBeInTheDocument();
        expect(within(empty).getByTestId('todo-list-empty-create')).toBeInTheDocument();
    });

    it('ボードでも、すべての列が空なら同じ案内を出す', async () => {
        renderList({ status: 200, body: { ...pageOf([]), total: 0 } }, { path: '/alpha/todos?view=board&scope=assigned' });
        expect(await screen.findByTestId('todo-list-empty')).toHaveTextContent('自分が担当の ToDo はありません。');
        expect(screen.queryByTestId('todo-board-columns')).toBeNull();
    });
});

describe('ToDo 一覧画面: 狭い画面 (md 未満) のカード表示', () => {
    it('md 未満の幅では表ではなくカードを並べ、同じ情報と操作を出す', async () => {
        await page.viewport(600, 900);
        const user = userEvent.setup();
        const todo = todoOf({ checklist: { done_count: 3, total_count: 5 }, comment_count: 2, creator: { id: OTHER_USER_ID, display_name: 'Taro Yamada', is_active: false } });
        renderList({ status: 200, body: pageOf([todo, OTHERS]) }, { roles: ['member'] });
        expect(await screen.findByTestId('todo-card-list')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-table')).toBeNull();
        expect(screen.getByTestId('todo-list-content')).toHaveAttribute('data-layout', 'cards');
        const card = screen.getByTestId(`todo-card-${MINE.id}`);
        expect(within(card).getByTestId(`todo-link-${MINE.id}`)).toHaveAttribute('href', `/alpha/todos/${MINE.id}`);
        expect(within(card).getByTestId(`todo-progress-${MINE.id}`)).toHaveTextContent('3/5');
        expect(within(card).getByTestId(`todo-comments-${MINE.id}`)).toHaveTextContent('2');
        expect(within(card).getByTestId(`todo-creator-${MINE.id}`)).toHaveTextContent('作成者: Taro Yamada (無効)');
        expect(within(card).getByTestId(`todo-due-${MINE.id}`)).toHaveTextContent('2026-11-01');
        // 権限のあるカードにはセレクト、無いカードにはチップ
        expect(within(card).getByTestId(`todo-status-select-${MINE.id}`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-status-chip-${SECOND_TODO_ID}`)).toHaveTextContent('未着手');
        expect(screen.getByTestId('todo-list-count')).toHaveTextContent('2 件を表示');
        await user.click(within(card).getByTestId(`todo-link-${MINE.id}`));
        expect(await screen.findByTestId('location-probe')).toHaveTextContent(`/alpha/todos/${MINE.id}`);
    });

    it('md 以上の幅では表を出す', async () => {
        renderList(PAGE);
        expect(await screen.findByTestId('todo-table')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-card-list')).toBeNull();
        expect(screen.getByTestId('todo-list-content')).toHaveAttribute('data-layout', 'table');
    });
});

describe('ToDo 一覧画面: 狭い幅でページ全体が横にはみ出さない', () => {
    /** 進捗・コメント数・長いタイトルを持つ ToDo (画面を広げやすい要素をそろえる) */
    const wide_todo = todoOf({
        title: 'とても長いタイトルの ToDo とても長いタイトルの ToDo とても長いタイトルの ToDo ToDo-with-a-very-long-unbreakable-word-0123456789012345678901234567890123456789',
        checklist: { done_count: 5, total_count: 5 },
        comment_count: 12,
        assignees: [assigneeOf({ display_name: 'Very Long Display Name Of Assignee Number One' }), assigneeOf({ user_id: THIRD_USER_ID, display_name: 'Jiro Suzuki', is_active: false })],
    });
    const partial_todo = todoOf({ id: SECOND_TODO_ID, title: '進捗の途中', checklist: { done_count: 1, total_count: 4 }, comment_count: 3 });

    it.each([
        ['リスト (カード)', '/alpha/todos', 'todo-card-list'],
        ['表示範囲のタブを切り替えた後', '/alpha/todos?scope=assigned', 'todo-card-list'],
        ['絞り込みを適用中', '/alpha/todos?status=open,in_progress&priority=high&q=見積', 'todo-card-list'],
    ])('%s', async (_name, path, test_id) => {
        await useMobileViewport();
        renderList({ status: 200, body: { ...pageOf([wide_todo, partial_todo], 'next-1'), total: 120 } }, { path });
        await screen.findByTestId(test_id);
        await vi.waitFor(() => expect(screen.getByTestId(`todo-progress-${wide_todo.id}`)).toBeInTheDocument());
        expect(pageOverflowOf()).toMatchObject({ ok: true });
    });

    it('タブを切り替えても、絞り込みを開いても、はみ出さない', async () => {
        await useMobileViewport();
        const user = userEvent.setup();
        renderList({ status: 200, body: pageOf([wide_todo, partial_todo]) });
        await screen.findByTestId('todo-card-list');
        await user.click(screen.getByTestId('todo-scope-shared'));
        await user.click(screen.getByTestId('todo-filter-toggle'));
        await vi.waitFor(() => expect(screen.getByTestId('todo-filter-priority')).toBeVisible());
        expect(pageOverflowOf()).toMatchObject({ ok: true });
    });

    it('ボード表示でも、列の横スクロールはコンテナの中に収まり、ページは広がらない', async () => {
        await useMobileViewport();
        renderList((request) => {
            const status = new URL(request.url).searchParams.get('status');
            // 画面の外 (2・3 列目) にあるカードの隠し文字もはみ出さないことを確かめるため、右の列に置く
            const items = [{ ...wide_todo, status: 'in_progress' as const }, { ...partial_todo, status: 'done' as const }].filter((todo) => todo.status === status);
            return { status: 200, body: { ...pageOf(items), total: items.length } };
        }, { path: '/alpha/todos?view=board' });
        const columns = await screen.findByTestId('todo-board-columns');
        await vi.waitFor(() => expect(screen.getByTestId(`todo-progress-${wide_todo.id}`)).toBeInTheDocument());
        expect(columns.scrollWidth).toBeGreaterThan(columns.clientWidth);
        expect(pageOverflowOf()).toMatchObject({ ok: true });
    });
});
