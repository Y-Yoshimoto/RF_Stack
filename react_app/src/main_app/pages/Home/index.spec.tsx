// AP ホームのテスト (機能への入口から ToDo へ遷移できる。ToDo の要約: 4 枚のカードと絞り込み済みの一覧へのリンク・期限の近い担当 ToDo・部分的な失敗)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { pageOverflowOf, resetViewport, useMobileViewport } from '@/shared/testing/page_overflow';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, summaryOf, todoOf } from '@/main_app/testing/todo_test_data';
import { AppHomePage } from '.';

const SUMMARY_KEY = 'GET /api/v1/todos/summary';
const LIST_KEY = 'GET /api/v1/todos';
const SECOND_TODO_ID = '01900000-0000-7000-8000-00000000c002';

afterEach(async () => {
    vi.restoreAllMocks();
    await resetViewport();
});

const UPCOMING = [
    todoOf({ title: '期限切れの請求書', due_date: '2026-10-20', assignees: [assigneeOf({ user_id: SELF_USER_ID })], created_by: OTHER_USER_ID, checklist: { done_count: 1, total_count: 3 } }),
    todoOf({ id: SECOND_TODO_ID, title: '見積もりを送る', due_date: '2026-11-02', assignees: [assigneeOf({ user_id: SELF_USER_ID })], priority: 'high' }),
];

/**
 * ホームを描画する関数
 * @param {Record<string, MockHandler>} replies 要約・一覧の応答
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderHome = (replies: Record<string, MockHandler> = {}) => {
    const spy = mockFetch({
        [SUMMARY_KEY]: { status: 200, body: summaryOf() },
        [LIST_KEY]: { status: 200, body: pageOf(UPCOMING) },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/" element={<AppHomePage />} />, { path: '/alpha/', roles: ['member'] });
    return spy;
};

describe('AP ホーム', () => {
    it('ToDo への入口を、準備中ではなくリンクとして表示する', async () => {
        renderHome();
        await screen.findByTestId('todo-summary-cards');
        const card = screen.getByTestId('app-home-feature-todo');
        expect(within(card).getByRole('link', { name: 'ToDo' })).toHaveAttribute('href', '/alpha/todos');
        expect(card).not.toHaveTextContent('準備中');
    });

    it('機能の入口は、ナビゲーションと同じ並び (ToDo → ユーザー管理 → 組織管理 → プロフィール) で出す', async () => {
        renderHome();
        await screen.findByTestId('todo-summary-cards');
        const labels = screen.getAllByTestId(/^app-home-feature-/).map((card) => card.textContent);
        expect(labels).toEqual(['ToDo', 'ユーザー管理', '組織管理', 'プロフィール']);
    });

    it('要約を、機能カードの上に出す (見出し ToDo の要約)', async () => {
        renderHome();
        const summary = await screen.findByTestId('todo-summary');
        expect(within(summary).getByRole('heading', { name: 'ToDo の要約' })).toBeInTheDocument();
        const features = screen.getByTestId('app-home-feature-todo');
        expect(summary.compareDocumentPosition(features) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
});

describe('ホームの ToDo の要約', () => {
    it('4 枚のカードに件数を出し、それぞれ絞り込み済みの一覧へのリンクにする', async () => {
        renderHome();
        await screen.findByTestId('todo-summary-cards');
        expect(screen.getByTestId('todo-summary-count-assigned_unfinished')).toHaveTextContent('4');
        expect(screen.getByTestId('todo-summary-count-assigned_overdue')).toHaveTextContent('1');
        expect(screen.getByTestId('todo-summary-count-assigned_due_soon')).toHaveTextContent('2');
        expect(screen.getByTestId('todo-summary-count-created_unfinished')).toHaveTextContent('2');
        const href = (key: string) => new URL(screen.getByTestId(`todo-summary-link-${key}`).getAttribute('href') ?? '', 'http://localhost');
        expect(href('assigned_unfinished').pathname).toBe('/alpha/todos');
        expect(Object.fromEntries(href('assigned_unfinished').searchParams)).toEqual({ scope: 'assigned', status: 'open,in_progress' });
        expect(Object.fromEntries(href('assigned_overdue').searchParams)).toEqual({ scope: 'assigned', status: 'open,in_progress', due_before: '2026-10-28', sort: 'due_date' });
        expect(Object.fromEntries(href('assigned_due_soon').searchParams)).toEqual({ scope: 'assigned', status: 'open,in_progress', due_after: '2026-10-29', due_before: '2026-11-05', sort: 'due_date' });
        expect(Object.fromEntries(href('created_unfinished').searchParams)).toEqual({ scope: 'mine', status: 'open,in_progress' });
        // リンクの名前は、見出しと件数を合わせたもの
        expect(screen.getByRole('link', { name: /^期限切れ\s*1\s*件$/ })).toBeInTheDocument();
    });

    it('期限切れがあるときは、色だけでなく警告アイコン付きの太字の文言でも示す。0 件なら強調しない', async () => {
        renderHome();
        await screen.findByTestId('todo-summary-cards');
        const overdue = screen.getByTestId('todo-summary-card-assigned_overdue');
        expect(overdue.querySelector('svg[data-testid="WarningAmberIcon"]')).not.toBeNull();
        expect(overdue).toHaveTextContent('期限切れ');
    });

    it('期限切れが 0 件なら、件数 0 を出す (リンクは残す)', async () => {
        renderHome({ [SUMMARY_KEY]: { status: 200, body: summaryOf({ assigned: { open: 0, in_progress: 0, overdue: 0, due_soon: 0 } }) } });
        await screen.findByTestId('todo-summary-cards');
        expect(screen.getByTestId('todo-summary-count-assigned_overdue')).toHaveTextContent('0');
        expect(screen.getByTestId('todo-summary-link-assigned_overdue')).toBeInTheDocument();
    });

    it('今日の日付を送って要約を取得する', async () => {
        const spy = renderHome();
        await screen.findByTestId('todo-summary-cards');
        const params = new URL(calledRequests(spy).find((request) => request.url.includes('/todos/summary'))?.url ?? '').searchParams;
        expect(params.get('today')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });

    it('期限の近い担当 ToDo を、期限順の担当 ToDo の上位 5 件として取得し、小さいカードで出す', async () => {
        const spy = renderHome();
        const list = await screen.findByTestId('todo-summary-upcoming-list');
        const request = calledRequests(spy).find((candidate) => candidate.url.includes('/todos?'));
        expect(Object.fromEntries(new URL(request?.url ?? '').searchParams)).toMatchObject({ scope: 'assigned', status: 'open,in_progress', sort: 'due_date', limit: '5' });
        const cards = within(list).getAllByTestId(/^todo-card-/);
        expect(cards).toHaveLength(2);
        const overdue_card = within(list).getByTestId(`todo-card-${UPCOMING[0].id}`);
        expect(within(overdue_card).getByTestId(`todo-link-${UPCOMING[0].id}`)).toHaveAttribute('href', `/alpha/todos/${UPCOMING[0].id}`);
        expect(within(overdue_card).getByTestId(`todo-due-${UPCOMING[0].id}`)).toHaveTextContent('期限切れ');
        expect(within(overdue_card).getByTestId(`todo-progress-${UPCOMING[0].id}`)).toHaveTextContent('1/3');
        // 小さいカード: ステータスのチップと作成者の行は出さない
        expect(within(overdue_card).queryByTestId(`todo-status-chip-${UPCOMING[0].id}`)).toBeNull();
        expect(within(overdue_card).queryByTestId(`todo-creator-${UPCOMING[0].id}`)).toBeNull();
    });

    it('「すべて見る」は、期限順の担当の未完了の一覧へのリンクにする', async () => {
        renderHome();
        const link = await screen.findByTestId('todo-summary-upcoming-all');
        const url = new URL(link.getAttribute('href') ?? '', 'http://localhost');
        expect(url.pathname).toBe('/alpha/todos');
        expect(Object.fromEntries(url.searchParams)).toEqual({ scope: 'assigned', status: 'open,in_progress', sort: 'due_date' });
    });

    it('期限の近い担当 ToDo が無ければ、その旨を出す', async () => {
        renderHome({ [LIST_KEY]: { status: 200, body: pageOf([]) } });
        expect(await screen.findByTestId('todo-summary-upcoming-empty')).toHaveTextContent('期限の近い担当の ToDo はありません。');
        expect(screen.getByTestId('todo-summary-upcoming-all')).toBeInTheDocument();
    });

    it('要約の取得に失敗しても、その部分だけにエラーと再試行を出し、他の部分は表示する。再試行で取り直す', async () => {
        const user = userEvent.setup();
        let calls = 0;
        renderHome({
            [SUMMARY_KEY]: () => {
                calls += 1;
                return calls === 1 ? problemReply(500, 'internal_error') : { status: 200, body: summaryOf() };
            },
        });
        const alert = await screen.findByTestId('todo-summary-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(screen.queryByTestId('todo-summary-cards')).toBeNull();
        // 期限の近い ToDo・ユーザー・機能の入口は表示される
        expect(await screen.findByTestId('todo-summary-upcoming-list')).toBeInTheDocument();
        expect(screen.getByTestId('app-home-user')).toBeInTheDocument();
        expect(screen.getByTestId('app-home-feature-todo')).toBeInTheDocument();
        await user.click(screen.getByTestId('todo-summary-error-reload'));
        expect(await screen.findByTestId('todo-summary-cards')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-summary-error')).toBeNull();
    });

    it('期限の近い ToDo の取得に失敗しても、要約のカードは表示する', async () => {
        renderHome({ [LIST_KEY]: problemReply(500, 'internal_error') });
        expect(await screen.findByTestId('todo-summary-upcoming-error')).toHaveAttribute('role', 'alert');
        expect(await screen.findByTestId('todo-summary-cards')).toBeInTheDocument();
        expect(screen.getByTestId('todo-summary-upcoming-error-reload')).toBeInTheDocument();
    });

    it('狭い幅 (Pixel 5 相当) でも、進捗・コメント数付きのカードでページ全体が横にはみ出さない', async () => {
        await useMobileViewport();
        renderHome({ [LIST_KEY]: { status: 200, body: pageOf(UPCOMING.map((todo) => ({ ...todo, checklist: { done_count: 3, total_count: 3 }, comment_count: 12 }))) } });
        await screen.findByTestId('todo-summary-upcoming-list');
        await screen.findByTestId('todo-summary-cards');
        expect(pageOverflowOf()).toMatchObject({ ok: true });
    });
});
