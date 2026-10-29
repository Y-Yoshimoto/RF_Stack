// ToDo のカンバン (ボード表示) のテスト (列と総件数・掴めないカード・カードのメニューでの変更・キーボードでの移動・失敗の巻き戻し・列ごとの無限スクロール・モバイルの横スクロール)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page } from 'vitest/browser';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { OTHER_USER_ID, SELF_USER_ID, organizationOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_USERS, THIRD_USER_ID, meBodyOf, pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, todoDetailOf, todoOf } from '@/main_app/testing/todo_test_data';
import { AppTodoListPage } from '..';
import { TODO_BOARD_LOCKED_TEXT } from './TodoDraggableCard';

const SECOND_TODO_ID = '01900000-0000-7000-8000-00000000c002';
const THIRD_TODO_ID = '01900000-0000-7000-8000-00000000c003';
const FOURTH_TODO_ID = '01900000-0000-7000-8000-00000000c004';

afterEach(async () => {
    vi.restoreAllMocks();
    await page.viewport(1280, 720);
});

/** 自分が作成した未着手、他人が作成し自分が担当の進行中、他人が作成し自分に無関係の進行中、完了 */
const MINE = todoOf({ title: '自分の ToDo', status: 'open', created_by: SELF_USER_ID, assignees: [] });
const ASSIGNED = todoOf({ id: SECOND_TODO_ID, title: '担当している ToDo', status: 'in_progress', created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: SELF_USER_ID })], checklist: { done_count: 1, total_count: 4 }, comment_count: 3 });
const OTHERS = todoOf({ id: THIRD_TODO_ID, title: '他人の ToDo', status: 'in_progress', created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: THIRD_USER_ID, display_name: 'Jiro Suzuki' })], due_date: null });
const FINISHED = todoOf({ id: FOURTH_TODO_ID, title: '終わった ToDo', status: 'done', created_by: SELF_USER_ID, assignees: [] });
const ALL = [MINE, ASSIGNED, OTHERS, FINISHED];

/** ステータス (列) ごとに ToDo と総件数を返す応答 */
const columnReply = (todos: typeof ALL) => (request: Request) => {
    const status = new URL(request.url).searchParams.get('status');
    const items = todos.filter((todo) => todo.status === status);
    return { status: 200, body: { ...pageOf(items), total: items.length } };
};

/**
 * ボード表示で一覧画面を描画する関数
 * @param {MockHandler} reply 一覧 API の応答
 * @param {{ roles?: string[]; replies?: Record<string, MockHandler> }} options ロール・追加の応答
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderBoard = (reply: MockHandler, { roles = ['tenant_admin'], replies = {} }: { roles?: string[]; replies?: Record<string, MockHandler> } = {}) => {
    const spy = mockFetch({
        'GET /api/v1/todos': reply,
        'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles) },
        'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) },
        'GET /api/v1/organizations': { status: 200, body: pageOf([organizationOf()]) },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/todos" element={<AppTodoListPage />} />, { path: '/alpha/todos?view=board', roles });
    return spy;
};

/** 列の中のカードの ToDo ID を並び順に返す関数 */
const cardIdsIn = (status: string): string[] => within(screen.getByTestId(`todo-board-column-${status}`)).queryAllByTestId(/^todo-board-card-/).map((card) => card.dataset.testid?.replace('todo-board-card-', '') ?? '');

describe('ToDo のカンバン', () => {
    it('ステータスの 3 列に、見出しと総件数、カードを出す。列は見出しで名前が付く', async () => {
        renderBoard(columnReply(ALL));
        await vi.waitFor(() => expect(screen.getByTestId('todo-board-count-done')).toBeInTheDocument());
        expect(screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)).toEqual(expect.arrayContaining(['未着手', '進行中', '完了']));
        expect(screen.getByRole('group', { name: '進行中' })).toBe(screen.getByTestId('todo-board-column-in_progress'));
        expect(screen.getByTestId('todo-board-count-open')).toHaveTextContent('1 件');
        expect(screen.getByTestId('todo-board-count-in_progress')).toHaveTextContent('2 件');
        expect(cardIdsIn('open')).toEqual([MINE.id]);
        expect(cardIdsIn('in_progress')).toEqual([ASSIGNED.id, OTHERS.id]);
        expect(cardIdsIn('done')).toEqual([FINISHED.id]);
        expect(screen.getByTestId('todo-board-in_progress-count')).toHaveTextContent('2 件中 2 件を表示');
        // カードに進捗・コメント数・期限・担当者を出す
        expect(screen.getByTestId(`todo-progress-${ASSIGNED.id}`)).toHaveTextContent('1/4');
        expect(screen.getByTestId(`todo-comments-${ASSIGNED.id}`)).toHaveTextContent('3');
        expect(screen.getByTestId(`todo-assignees-${OTHERS.id}`)).toHaveTextContent('担当: Jiro Suzuki');
        expect(screen.getByTestId(`todo-link-${MINE.id}`)).toHaveAttribute('href', `/alpha/todos/${MINE.id}`);
    });

    it('列に ToDo が無ければ、その列に案内を出す', async () => {
        renderBoard(columnReply([MINE]));
        expect(await screen.findByTestId('todo-board-empty-done')).toHaveTextContent('「完了」の ToDo はありません。');
        expect(screen.getByTestId('todo-board-count-done')).toHaveTextContent('0 件');
    });

    it('テナント管理者は、すべてのカードを掴める (ハンドルに aria-disabled が付かない)', async () => {
        renderBoard(columnReply(ALL));
        await screen.findByTestId(`todo-board-handle-${OTHERS.id}`);
        for (const todo of ALL) {
            const handle = screen.getByTestId(`todo-board-handle-${todo.id}`);
            expect(handle).toHaveAttribute('aria-disabled', 'false');
            expect(handle).toHaveAttribute('aria-roledescription', 'ドラッグできるカード');
            expect(handle).toHaveAttribute('data-locked', 'false');
            expect(screen.getByTestId(`todo-board-menu-${todo.id}`)).toBeInTheDocument();
        }
    });

    it('メンバーは、作成者・担当者のカードだけ掴める。他のカードは鍵アイコンで aria-disabled、理由をツールチップと名前で示し、メニューも出さない', async () => {
        const user = userEvent.setup();
        renderBoard(columnReply(ALL), { roles: ['member'] });
        await screen.findByTestId(`todo-board-handle-${OTHERS.id}`);
        await vi.waitFor(() => expect(screen.getByTestId(`todo-board-handle-${MINE.id}`)).toHaveAttribute('aria-disabled', 'false'));
        expect(screen.getByTestId(`todo-board-handle-${ASSIGNED.id}`)).toHaveAttribute('aria-disabled', 'false');
        const locked = screen.getByTestId(`todo-board-handle-${OTHERS.id}`);
        expect(locked).toHaveAttribute('aria-disabled', 'true');
        expect(locked).toHaveAttribute('data-locked', 'true');
        expect(locked).toHaveAccessibleName(`「他人の ToDo」は移動できません。${TODO_BOARD_LOCKED_TEXT}`);
        expect(screen.getByTestId(`todo-board-card-${OTHERS.id}`)).toHaveAttribute('data-draggable', 'false');
        expect(screen.queryByTestId(`todo-board-menu-${OTHERS.id}`)).toBeNull();
        await user.hover(locked);
        expect(await screen.findByRole('tooltip')).toHaveTextContent('ステータスを変更できるのは作成者・担当者・テナント管理者です');
    });

    it('自分の ID (useMe) を取得できるまでは、テナント管理者でも全カードを掴めない', async () => {
        renderBoard(columnReply(ALL), { replies: { 'GET /api/v1/me': problemReply(500, 'internal_error') } });
        await screen.findByTestId(`todo-board-handle-${MINE.id}`);
        for (const todo of ALL) expect(screen.getByTestId(`todo-board-handle-${todo.id}`)).toHaveAttribute('aria-disabled', 'true');
    });

    it('カードのメニューでステータスを変えると、If-Match 付きで status だけを送り、カードを移して知らせる', async () => {
        const user = userEvent.setup();
        const spy = renderBoard(columnReply(ALL), {
            replies: { [`PATCH /api/v1/todos/${MINE.id}`]: { status: 200, body: todoDetailOf({ ...MINE, status: 'done', version: 4 }), headers: { ETag: '"4"' } } },
        });
        await screen.findByTestId(`todo-board-menu-${MINE.id}`);
        await user.click(screen.getByTestId(`todo-board-menu-${MINE.id}`));
        const panel = await screen.findByTestId(`todo-board-menu-panel-${MINE.id}`);
        await user.click(within(within(panel).getByTestId(`todo-status-select-${MINE.id}`)).getByRole('combobox'));
        await user.click(screen.getByTestId(`todo-status-option-${MINE.id}-done`));
        expect(await screen.findByTestId('todo-list-notice')).toHaveTextContent('「自分の ToDo」のステータスを「完了」に変更しました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ status: 'done' });
        await vi.waitFor(() => expect(cardIdsIn('done').sort()).toEqual([MINE.id, FINISHED.id].sort()));
        expect(cardIdsIn('open')).toEqual([]);
        expect(screen.getByTestId('todo-board-count-done')).toHaveTextContent('2 件');
        expect(screen.getByTestId('todo-board-count-open')).toHaveTextContent('0 件');
    });

    it('キーボードで、ハンドルを持ち上げて右矢印で隣の列へ置くと、ステータスが変わる。読み上げの通知も日本語', async () => {
        const user = userEvent.setup();
        const spy = renderBoard(columnReply(ALL), {
            replies: { [`PATCH /api/v1/todos/${MINE.id}`]: { status: 200, body: todoDetailOf({ ...MINE, status: 'in_progress', version: 4 }), headers: { ETag: '"4"' } } },
        });
        const handle = await screen.findByTestId(`todo-board-handle-${MINE.id}`);
        await vi.waitFor(() => expect(handle).toHaveAttribute('aria-disabled', 'false'));
        expect(handle).toHaveAccessibleDescription(/カードを移すには、スペースキーまたは Enter キーで持ち上げ/);
        handle.focus();
        await user.keyboard(' ');
        // 持ち上げた直後に、今いる列の上にある通知で置き換わる
        await vi.waitFor(() => expect(document.body).toHaveTextContent('「自分の ToDo」を「未着手」の列の上に動かしました。'));
        await user.keyboard('{ArrowRight}');
        await vi.waitFor(() => expect(document.body).toHaveTextContent('「自分の ToDo」を「進行中」の列の上に動かしました。'));
        await user.keyboard(' ');
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => request.method === 'PATCH')).toBe(true));
        expect(await calledRequests(spy).find((request) => request.method === 'PATCH')?.json()).toEqual({ status: 'in_progress' });
        await vi.waitFor(() => expect(cardIdsIn('in_progress')).toContain(MINE.id));
        expect(cardIdsIn('open')).toEqual([]);
    });

    it('マウスでカードを隣の列へドラッグすると、ステータスが変わる', async () => {
        const user = userEvent.setup();
        const spy = renderBoard(columnReply(ALL), {
            replies: { [`PATCH /api/v1/todos/${MINE.id}`]: { status: 200, body: todoDetailOf({ ...MINE, status: 'in_progress', version: 4 }), headers: { ETag: '"4"' } } },
        });
        const card = await screen.findByTestId(`todo-board-card-${MINE.id}`);
        await vi.waitFor(() => expect(screen.getByTestId(`todo-board-handle-${MINE.id}`)).toHaveAttribute('aria-disabled', 'false'));
        const target = screen.getByTestId('todo-board-column-in_progress');
        const from = card.getBoundingClientRect();
        const to = target.getBoundingClientRect();
        const start = { clientX: from.left + from.width / 2, clientY: from.top + from.height / 2 };
        await user.pointer([
            { keys: '[MouseLeft>]', target: card, coords: start },
            { coords: { clientX: start.clientX + 12, clientY: start.clientY + 4 } },
            { target, coords: { clientX: to.left + to.width / 2, clientY: to.top + 80 } },
            { keys: '[/MouseLeft]' },
        ]);
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => request.method === 'PATCH')).toBe(true));
        expect(await calledRequests(spy).find((request) => request.method === 'PATCH')?.json()).toEqual({ status: 'in_progress' });
        await vi.waitFor(() => expect(cardIdsIn('in_progress')).toContain(MINE.id));
    });

    it('カードのタイトルのリンクは、クリックでそのまま詳細へ移れる (6px 動かすまではドラッグにならない)', async () => {
        const user = userEvent.setup();
        renderBoard(columnReply(ALL));
        await user.click(await screen.findByTestId(`todo-link-${MINE.id}`));
        expect(await screen.findByTestId('location-probe')).toHaveTextContent(`/alpha/todos/${MINE.id}`);
    });

    it('掴めないカードは、ドラッグしても移動しない', async () => {
        const user = userEvent.setup();
        const spy = renderBoard(columnReply(ALL), { roles: ['member'] });
        const card = await screen.findByTestId(`todo-board-card-${OTHERS.id}`);
        await vi.waitFor(() => expect(screen.getByTestId(`todo-board-handle-${MINE.id}`)).toHaveAttribute('aria-disabled', 'false'));
        const target = screen.getByTestId('todo-board-column-done');
        const from = card.getBoundingClientRect();
        const to = target.getBoundingClientRect();
        const start = { clientX: from.left + from.width / 2, clientY: from.top + from.height / 2 };
        await user.pointer([
            { keys: '[MouseLeft>]', target: card, coords: start },
            { coords: { clientX: start.clientX + 12, clientY: start.clientY + 4 } },
            { target, coords: { clientX: to.left + to.width / 2, clientY: to.top + 80 } },
            { keys: '[/MouseLeft]' },
        ]);
        expect(calledRequests(spy).some((request) => request.method === 'PATCH')).toBe(false);
        expect(cardIdsIn('in_progress')).toContain(OTHERS.id);
    });

    it('Escape で取り消すと、ステータスは変わらない', async () => {
        const user = userEvent.setup();
        const spy = renderBoard(columnReply(ALL));
        const handle = await screen.findByTestId(`todo-board-handle-${MINE.id}`);
        await vi.waitFor(() => expect(handle).toHaveAttribute('aria-disabled', 'false'));
        handle.focus();
        await user.keyboard(' ');
        await user.keyboard('{ArrowRight}');
        await user.keyboard('{Escape}');
        await vi.waitFor(() => expect(document.body).toHaveTextContent('移動を取り消しました。「自分の ToDo」は「未着手」の列のままです。'));
        expect(calledRequests(spy).some((request) => request.method === 'PATCH')).toBe(false);
        expect(cardIdsIn('open')).toEqual([MINE.id]);
    });

    it('移動に失敗すると、カードを元の列に戻し、role="alert" で理由を知らせる。再読み込みで列を取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderBoard(columnReply(ALL), { replies: { [`PATCH /api/v1/todos/${MINE.id}`]: problemReply(412, 'todo_version_conflict') } });
        await screen.findByTestId(`todo-board-menu-${MINE.id}`);
        await user.click(screen.getByTestId(`todo-board-menu-${MINE.id}`));
        const panel = await screen.findByTestId(`todo-board-menu-panel-${MINE.id}`);
        await user.click(within(within(panel).getByTestId(`todo-status-select-${MINE.id}`)).getByRole('combobox'));
        await user.click(screen.getByTestId(`todo-status-option-${MINE.id}-done`));
        const alert = await screen.findByTestId('todo-board-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('他の操作で更新されています');
        await vi.waitFor(() => expect(cardIdsIn('open')).toEqual([MINE.id]));
        expect(cardIdsIn('done')).toEqual([FINISHED.id]);
        const before = calledRequests(spy).filter((request) => request.method === 'GET' && request.url.includes('/todos')).length;
        await user.click(screen.getByTestId('todo-board-error-reload'));
        await vi.waitFor(() => expect(calledRequests(spy).filter((request) => request.method === 'GET' && request.url.includes('/todos')).length).toBeGreaterThan(before));
        await vi.waitFor(() => expect(screen.queryByTestId('todo-board-error')).toBeNull());
    });

    it('列ごとに末尾が見えたら続きを読み込み、総件数を保つ', async () => {
        renderBoard((request) => {
            const params = new URL(request.url).searchParams;
            if (params.get('status') !== 'open') return { status: 200, body: { ...pageOf([]), total: 0 } };
            return params.get('cursor') === null
                ? { status: 200, body: { ...pageOf([MINE], 'next-open'), total: 2 } }
                : { status: 200, body: pageOf([todoOf({ id: FOURTH_TODO_ID, title: '2 ページ目の ToDo', status: 'open' })], null) };
        });
        await vi.waitFor(() => expect(cardIdsIn('open')).toEqual([MINE.id, FOURTH_TODO_ID]));
        expect(screen.getByTestId('todo-board-open-count')).toHaveTextContent('2 件中 2 件を表示');
        expect(screen.getByTestId('todo-board-count-open')).toHaveTextContent('2 件');
        expect(screen.queryByTestId('todo-board-open-load-more')).toBeNull();
    });

    it('列の続きの読み込みに失敗したら、その列に再試行を出す', async () => {
        const user = userEvent.setup();
        let second_calls = 0;
        renderBoard((request) => {
            const params = new URL(request.url).searchParams;
            if (params.get('status') !== 'open') return { status: 200, body: { ...pageOf([]), total: 0 } };
            if (params.get('cursor') === null) return { status: 200, body: { ...pageOf([MINE], 'next-open'), total: 2 } };
            second_calls += 1;
            return second_calls === 1 ? problemReply(500, 'internal_error') : { status: 200, body: pageOf([todoOf({ id: FOURTH_TODO_ID, status: 'open' })], null) };
        });
        expect(await screen.findByTestId('todo-board-open-load-more-error')).toHaveAttribute('role', 'alert');
        await user.click(screen.getByTestId('todo-board-open-load-more'));
        await vi.waitFor(() => expect(cardIdsIn('open')).toEqual([MINE.id, FOURTH_TODO_ID]));
    });

    it('列の取得に失敗したら、その列だけにエラーと再試行を出し、他の列は表示する', async () => {
        renderBoard((request) => {
            const status = new URL(request.url).searchParams.get('status');
            return status === 'done' ? problemReply(500, 'internal_error') : columnReply(ALL)(request);
        });
        const alert = await screen.findByTestId('todo-board-column-error-done');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(within(alert).getByTestId('todo-board-column-error-done-reload')).toBeInTheDocument();
        await vi.waitFor(() => expect(cardIdsIn('open')).toEqual([MINE.id]));
    });

    it('md 未満では列を横スクロール (scroll-snap) にし、1 列を画面幅の 85% にする', async () => {
        await page.viewport(600, 900);
        renderBoard(columnReply(ALL));
        const columns = await screen.findByTestId('todo-board-columns');
        await vi.waitFor(() => expect(screen.getByTestId('todo-board-count-done')).toBeInTheDocument());
        const style = getComputedStyle(columns);
        expect(style.overflowX).toBe('auto');
        expect(style.scrollSnapType).toContain('x');
        expect(screen.getByTestId('todo-board-column-open').getBoundingClientRect().width).toBeCloseTo(window.innerWidth * 0.85, 0);
        expect(columns.scrollWidth).toBeGreaterThan(columns.clientWidth);
    });

    it('md 以上では 3 列を横に並べ、横スクロールにしない', async () => {
        renderBoard(columnReply(ALL));
        const columns = await screen.findByTestId('todo-board-columns');
        await vi.waitFor(() => expect(screen.getByTestId('todo-board-count-done')).toBeInTheDocument());
        expect(getComputedStyle(columns).scrollSnapType).toBe('none');
        const [open, in_progress, done] = ['open', 'in_progress', 'done'].map((status) => screen.getByTestId(`todo-board-column-${status}`).getBoundingClientRect());
        expect(open.right).toBeLessThanOrEqual(in_progress.left);
        expect(in_progress.right).toBeLessThanOrEqual(done.left);
        expect(columns.scrollWidth).toBeLessThanOrEqual(columns.clientWidth);
    });
});
