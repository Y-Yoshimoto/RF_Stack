// useTodoList / useTodoActivities / 選択肢のフックのテスト (カーソル・絞り込みの引き継ぎ・カーソル不正・全ページの取得)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { TodoListFilter } from '@/main_app/api/todos';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, ORGANIZATION_ID, organizationOf, OTHER_USER_ID, SELF_USER_ID, userOf } from '@/main_app/testing/app_test_support';
import { activityOf, assigneeOf, TODO_ID, todoOf } from '@/main_app/testing/todo_test_data';
import { calledRequests, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { parseTodoListSearch } from './list_search';
import { useTodoActivities } from './useTodoActivities';
import { useTodoAssigneeChoices, useTodoOrganizationChoices } from './useTodoChoices';
import { useTodoList } from './useTodoList';

const LIST_KEY = 'GET /api/v1/todos';
const ACTIVITIES_KEY = `GET /api/v1/todos/${TODO_ID}/activities`;

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * cursor に応じてページを返す応答を作る関数
 * @param {Record<string, MockReply>} pages cursor (先頭ページは '') → 応答
 * @returns {(request: Request) => MockReply} 応答関数
*/
const pagedReply = (pages: Record<string, MockReply>) => (request: Request): MockReply => {
    return pages[new URL(request.url).searchParams.get('cursor') ?? ''] ?? problemReply(422, 'validation_error');
};

const paramsOf = (spy: ReturnType<typeof mockFetch>, path: string) => calledRequests(spy).filter((request) => new URL(request.url).pathname === path).map((request) => new URL(request.url).searchParams);

const INVALID_CURSOR: MockReply = {
    status: 422,
    body: { type: 'about:blank', title: 'x', status: 422, detail: 'x', instance: '/', code: 'validation_error', errors: [{ field: 'cursor', code: 'invalid_cursor', message: 'x' }] },
};

describe('useTodoList', () => {
    it('URL クエリから作った絞り込みで取得し、loadMore で next_cursor を使って連結する (絞り込みは 2 ページ目にも付ける)', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(['member']),
            [LIST_KEY]: pagedReply({
                '': { status: 200, body: { items: [todoOf({ id: 'a' }), todoOf({ id: 'b' })], next_cursor: 'c1', total: null } },
                c1: { status: 200, body: { items: [todoOf({ id: 'b' }), todoOf({ id: 'c' })], next_cursor: null, total: null } },
            }),
        });
        const filter: TodoListFilter = { ...parseTodoListSearch(`scope=assigned&status=open,in_progress&assignee_id=${OTHER_USER_ID}&sort=due_date`), limit: 2 };
        const { result } = renderHook(() => useTodoList(filter), { wrapper: AppTestProvider });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b']);
        expect(result.current.total).toBeNull();

        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.has_more).toBe(false));
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b', 'c']);

        const [first, second] = paramsOf(spy, '/api/v1/todos');
        expect(first.toString()).toBe(`limit=2&scope=assigned&status=open%2Cin_progress&assignee_id=${OTHER_USER_ID}&sort=due_date`);
        expect(second.get('cursor')).toBe('c1');
        expect([second.get('scope'), second.get('status'), second.get('assignee_id'), second.get('sort')]).toEqual(['assigned', 'open,in_progress', OTHER_USER_ID, 'due_date']);
    });

    it('表示範囲が変わると先頭ページから取り直す。同じ意味の指定では取り直さない', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: (request) => ({ status: 200, body: { items: [todoOf({ id: new URL(request.url).searchParams.get('scope') ?? 'all' })], next_cursor: null } }),
        });
        const { result, rerender } = renderHook(({ filter }: { filter: TodoListFilter }) => useTodoList(filter), { wrapper: AppTestProvider, initialProps: { filter: {} } });
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['all']));
        rerender({ filter: { scope: 'all', status: [] } });
        expect(result.current.status).toBe('success');
        rerender({ filter: { scope: 'mine' } });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['mine']));
        expect(paramsOf(spy, '/api/v1/todos').map((params) => params.get('scope'))).toEqual([null, 'mine']);
    });

    it('次のページの invalid_cursor は読み込み済みを残し、requires_reload の load_more_error にする', async () => {
        mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: pagedReply({ '': { status: 200, body: { items: [todoOf({ id: 'a' })], next_cursor: 'broken' } }, broken: INVALID_CURSOR }),
        });
        const { result } = renderHook(() => useTodoList(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.load_more_error).not.toBeNull());
        expect(result.current.load_more_error).toMatchObject({ kind: 'invalid_input', requires_reload: true });
        expect(result.current.items.map((item) => item.id)).toEqual(['a']);
    });

    it('先頭ページの 422 (不正な絞り込み) は error', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [LIST_KEY]: problemReply(422, 'invalid_todo_input') });
        const { result } = renderHook(() => useTodoList({ q: 'x' }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'invalid_input', code: 'invalid_todo_input' });
    });
});

describe('useTodoActivities', () => {
    it('新しい順のページをカーソルで連結し、reload で先頭から取り直す', async () => {
        let first_calls = 0;
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [ACTIVITIES_KEY]: (request) => {
                if (new URL(request.url).searchParams.get('cursor') === 'c1') return { status: 200, body: { items: [activityOf({ id: 'old' })], next_cursor: null } };
                first_calls += 1;
                return { status: 200, body: { items: [activityOf({ id: `new${first_calls}`, action: 'status_changed' })], next_cursor: 'c1' } };
            },
        });
        const { result } = renderHook(() => useTodoActivities(TODO_ID, { limit: 1 }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['new1', 'old']));
        act(() => result.current.reload());
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['new2']));
        expect(paramsOf(spy, `/api/v1/todos/${TODO_ID}/activities`).map((params) => params.toString())).toEqual(['limit=1', 'limit=1&cursor=c1', 'limit=1']);
    });

    it('閲覧できない ToDo は 404 todo_not_found', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [ACTIVITIES_KEY]: problemReply(404, 'todo_not_found') });
        const { result } = renderHook(() => useTodoActivities(TODO_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'not_found', code: 'todo_not_found' });
    });
});

describe('選択肢のフック', () => {
    it('担当者: ユーザー一覧の全ページを取得し、無効なユーザーは割り当て済みのものだけ残す', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(['member']),
            'GET /api/v1/users': pagedReply({
                '': { status: 200, body: { items: [userOf({ id: SELF_USER_ID, display_name: 'Self' }), userOf({ id: 'x', is_active: false })], next_cursor: 'c1' } },
                c1: { status: 200, body: { items: [userOf({ id: OTHER_USER_ID, is_active: false })], next_cursor: null } },
            }),
        });
        const assigned = [assigneeOf({ is_active: false })];
        const { result } = renderHook(() => useTodoAssigneeChoices(assigned), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.options.map((option) => [option.user_id, option.is_active, option.is_assigned])).toEqual([[SELF_USER_ID, true, false], [OTHER_USER_ID, false, true]]);
        expect(paramsOf(spy, '/api/v1/users').map((params) => params.get('limit'))).toEqual(['200', '200']);
    });

    it('公開先組織: 組織一覧の失敗は error', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), 'GET /api/v1/organizations': problemReply(503, 'service_unavailable') });
        const { result } = renderHook(() => useTodoOrganizationChoices(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'unavailable' });
    });

    it('公開先組織: 現在の公開先を選択済みにする', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), 'GET /api/v1/organizations': { status: 200, body: { items: [organizationOf()], next_cursor: null } } });
        const selected = [{ id: ORGANIZATION_ID, name: '営業部' }];
        const { result } = renderHook(() => useTodoOrganizationChoices(selected), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.options).toEqual([{ organization_id: ORGANIZATION_ID, name: '営業部', is_selected: true }]);
    });
});
