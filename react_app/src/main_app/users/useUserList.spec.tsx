// useUserList のテスト (カーソルの連結・絞り込み・カーソル不正・要素の置き換え)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { UserListFilter } from '@/main_app/api/users';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, userOf } from '@/main_app/testing/app_test_support';
import { calledRequests, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { useUserList } from './useUserList';

const LIST_KEY = 'GET /api/v1/users';

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

const listRequests = (spy: ReturnType<typeof mockFetch>) => calledRequests(spy).filter((request) => new URL(request.url).pathname === '/api/v1/users').map((request) => new URL(request.url).searchParams);

const INVALID_CURSOR: MockReply = {
    status: 422,
    body: { type: 'about:blank', title: 'x', status: 422, detail: 'x', instance: '/', code: 'validation_error', errors: [{ field: 'cursor', code: 'invalid_cursor', message: 'x' }] },
};

describe('useUserList', () => {
    it('先頭ページを取得し、loadMore で next_cursor を使って連結する (絞り込みは 2 ページ目にも付ける)', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(['member']),
            [LIST_KEY]: pagedReply({
                '': { status: 200, body: { items: [userOf({ id: 'a' }), userOf({ id: 'b' })], next_cursor: 'c1', total: null } },
                c1: { status: 200, body: { items: [userOf({ id: 'b' }), userOf({ id: 'c' })], next_cursor: null, total: null } },
            }),
        });
        const filter: UserListFilter = { sort: '-created_at', is_active: true, limit: 2 };
        const { result } = renderHook(() => useUserList(filter), { wrapper: AppTestProvider });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b']);
        expect(result.current.has_more).toBe(true);
        expect(result.current.total).toBeNull();

        act(() => result.current.loadMore());
        expect(result.current.is_loading_more).toBe(true);
        await waitFor(() => expect(result.current.is_loading_more).toBe(false));
        // 同じ ID は先に読み込んだものを残す
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b', 'c']);
        expect(result.current.has_more).toBe(false);

        const [first, second] = listRequests(spy);
        expect(first.toString()).toBe('limit=2&sort=-created_at&is_active=true');
        expect(second.get('cursor')).toBe('c1');
        expect(second.get('sort')).toBe('-created_at');
        expect(second.get('is_active')).toBe('true');
    });

    it('最後のページ・取得中は loadMore で何もしない', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: pagedReply({
                '': { status: 200, body: { items: [userOf({ id: 'a' })], next_cursor: 'c1' } },
                c1: { status: 200, body: { items: [userOf({ id: 'b' })], next_cursor: null } },
            }),
        });
        const { result } = renderHook(() => useUserList(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => {
            result.current.loadMore();
            result.current.loadMore();
        });
        await waitFor(() => expect(result.current.has_more).toBe(false));
        act(() => result.current.loadMore());
        expect(listRequests(spy)).toHaveLength(2);
    });

    it('絞り込みが変わると先頭ページから取り直す', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: (request) => {
                const is_active = new URL(request.url).searchParams.get('is_active');
                return { status: 200, body: { items: [userOf({ id: is_active === 'false' ? 'inactive' : 'all', is_active: is_active !== 'false' })], next_cursor: null } };
            },
        });
        const { result, rerender } = renderHook(({ filter }: { filter: UserListFilter }) => useUserList(filter), { wrapper: AppTestProvider, initialProps: { filter: {} } });
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['all']));
        rerender({ filter: { is_active: false } });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['inactive']));
        expect(listRequests(spy).map((params) => params.get('is_active'))).toEqual([null, 'false']);
    });

    it('次のページの invalid_cursor は読み込み済みを残し、requires_reload の load_more_error にする', async () => {
        mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: pagedReply({ '': { status: 200, body: { items: [userOf({ id: 'a' })], next_cursor: 'broken' } }, broken: INVALID_CURSOR }),
        });
        const { result } = renderHook(() => useUserList(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.load_more_error).not.toBeNull());
        expect(result.current.load_more_error).toMatchObject({ kind: 'invalid_input', status: 422, requires_reload: true });
        expect(result.current.items.map((item) => item.id)).toEqual(['a']);
        expect(result.current.status).toBe('success');
    });

    it('先頭ページの失敗は error (403 forbidden)', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [LIST_KEY]: problemReply(403, 'forbidden') });
        const { result } = renderHook(() => useUserList(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'forbidden', status: 403 });
    });

    it('replaceItem / removeItem で読み込み済みの要素を更新する', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [LIST_KEY]: { status: 200, body: { items: [userOf({ id: 'a' }), userOf({ id: 'b' })], next_cursor: null } } });
        const { result } = renderHook(() => useUserList(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.replaceItem(userOf({ id: 'b', is_active: false, version: 4 })));
        expect(result.current.items[1]).toMatchObject({ id: 'b', is_active: false, version: 4 });
        act(() => result.current.replaceItem(userOf({ id: 'unknown' })));
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b']);
        act(() => result.current.removeItem('a'));
        expect(result.current.items.map((item) => item.id)).toEqual(['b']);
    });
});
