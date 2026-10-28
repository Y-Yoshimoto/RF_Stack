// useTenantList のテスト (カーソルの連結・絞り込み・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { calledRequests, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { CP_STATUS_KEY, CpTestProvider, cpStatusReply, tenantItemOf } from '@/control_plane_app/testing/cp_test_support';
import type { TenantListFilter } from '@/control_plane_app/api/tenants';
import { appendTenantItems, useTenantList } from './useTenantList';

const LIST_KEY = 'GET /api/v1/cp/tenants';

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

const listRequests = (spy: ReturnType<typeof mockFetch>) => calledRequests(spy).filter((request) => new URL(request.url).pathname === '/api/v1/cp/tenants').map((request) => new URL(request.url).searchParams);

describe('useTenantList', () => {
    it('先頭ページを取得し、loadMore で next_cursor を使って連結する (総件数は先頭ページのみ要求)', async () => {
        const spy = mockFetch({
            [CP_STATUS_KEY]: cpStatusReply(),
            [LIST_KEY]: pagedReply({
                '': { status: 200, body: { items: [tenantItemOf('a'), tenantItemOf('b')], next_cursor: 'c1', total: 3 } },
                c1: { status: 200, body: { items: [tenantItemOf('c')], next_cursor: null, total: null } },
            }),
        });
        const filter: TenantListFilter = { status: ['SUSPENDED', 'ACTIVE', 'ACTIVE'], sort: 'name', include_total: true, limit: 2 };
        const { result } = renderHook(() => useTenantList(filter), { wrapper: CpTestProvider });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b']);
        expect(result.current.total).toBe(3);
        expect(result.current.has_more).toBe(true);

        act(() => result.current.loadMore());
        expect(result.current.is_loading_more).toBe(true);
        await waitFor(() => expect(result.current.is_loading_more).toBe(false));
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b', 'c']);
        expect(result.current.has_more).toBe(false);
        expect(result.current.total).toBe(3);

        const [first, second] = listRequests(spy);
        expect(first.get('status')).toBe('ACTIVE,SUSPENDED');
        expect(first.get('sort')).toBe('name');
        expect(first.get('include_total')).toBe('true');
        expect(first.get('limit')).toBe('2');
        expect(first.get('cursor')).toBeNull();
        expect(second.get('cursor')).toBe('c1');
        expect(second.get('status')).toBe('ACTIVE,SUSPENDED');
        expect(second.get('sort')).toBe('name');
        expect(second.get('include_total')).toBeNull();
    });

    it('最後のページ・取得中は loadMore で何もしない', async () => {
        const spy = mockFetch({
            [CP_STATUS_KEY]: cpStatusReply(),
            [LIST_KEY]: pagedReply({
                '': { status: 200, body: { items: [tenantItemOf('a')], next_cursor: 'c1' } },
                c1: { status: 200, body: { items: [tenantItemOf('b')], next_cursor: null } },
            }),
        });
        const { result } = renderHook(() => useTenantList(), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => {
            result.current.loadMore();
            result.current.loadMore();
        });
        await waitFor(() => expect(result.current.has_more).toBe(false));
        act(() => result.current.loadMore());
        expect(listRequests(spy)).toHaveLength(2);
        expect(result.current.items.map((item) => item.id)).toEqual(['a', 'b']);
    });

    it('絞り込みが変わると先頭ページから取り直す', async () => {
        const spy = mockFetch({
            [CP_STATUS_KEY]: cpStatusReply(),
            [LIST_KEY]: (request) => {
                const status = new URL(request.url).searchParams.get('status');
                return { status: 200, body: { items: [tenantItemOf(status ?? 'all')], next_cursor: null } };
            },
        });
        const { result, rerender } = renderHook(({ filter }) => useTenantList(filter), { wrapper: CpTestProvider, initialProps: { filter: {} as TenantListFilter } });
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['all']));
        rerender({ filter: { status: ['FAILED'] } });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['FAILED']));
        expect(listRequests(spy).map((params) => params.get('status'))).toEqual([null, 'FAILED']);
    });

    it('先頭ページの失敗は error (403 は forbidden)', async () => {
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [LIST_KEY]: problemReply(403, 'forbidden') });
        const { result } = renderHook(() => useTenantList(), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error?.kind).toBe('forbidden');
        expect(result.current.error?.code).toBe('forbidden');
        expect(result.current.items).toEqual([]);
    });

    it('次のページの失敗は読み込み済みを残し、不正なカーソルは requires_reload', async () => {
        mockFetch({
            [CP_STATUS_KEY]: cpStatusReply(),
            [LIST_KEY]: pagedReply({
                '': { status: 200, body: { items: [tenantItemOf('a')], next_cursor: 'broken' } },
                broken: { status: 422, body: { ...problemReply(422, 'validation_error').body as object, errors: [{ field: 'cursor', code: 'invalid_cursor', message: 'x' }] } },
            }),
        });
        const { result } = renderHook(() => useTenantList(), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.load_more_error).not.toBeNull());
        expect(result.current.load_more_error?.kind).toBe('invalid_input');
        expect(result.current.load_more_error?.requires_reload).toBe(true);
        expect(result.current.items.map((item) => item.id)).toEqual(['a']);
        expect(result.current.has_more).toBe(true);
    });
});

describe('appendTenantItems', () => {
    it('既に読み込んだ ID は重複させない', () => {
        expect(appendTenantItems([tenantItemOf('a')], [tenantItemOf('a'), tenantItemOf('b')]).map((item) => item.id)).toEqual(['a', 'b']);
    });
});
