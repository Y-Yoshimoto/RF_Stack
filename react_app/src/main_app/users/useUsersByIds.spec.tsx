// useUsersByIds のテスト (100 件ずつの分割取得・続きのページ・見つからない ID・UUID でない ID・失敗・取り直しの条件)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, OTHER_USER_ID, SELF_USER_ID, userOf } from '@/main_app/testing/app_test_support';
import { calledRequests, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { useUsersByIds } from './useUsersByIds';

const LIST_KEY = 'GET /api/v1/users';

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 連番のユーザー ID を作る関数 (UUID の形式)
 * @param {number} index 番号
 * @returns {string} ユーザー ID
*/
const idOf = (index: number): string => `01900000-0000-7000-8000-${index.toString(16).padStart(12, '0')}`;

/**
 * ids クエリのユーザーを返す応答 (known に含まれる ID だけを返す。存在しない・他テナントの ID は含まれない)
 * @param {(id: string) => boolean} known 存在する ID か
 * @returns {(request: Request) => MockReply} 応答関数
*/
const idsReply = (known: (id: string) => boolean = () => true) => (request: Request): MockReply => {
    const ids = (new URL(request.url).searchParams.get('ids') ?? '').split(',').filter((id) => id !== '');
    return { status: 200, body: { items: ids.filter(known).map((id) => userOf({ id, display_name: `user-${id.slice(-4)}` })), next_cursor: null } };
};

const listParams = (spy: ReturnType<typeof mockFetch>) => calledRequests(spy).filter((request) => new URL(request.url).pathname === '/api/v1/users').map((request) => new URL(request.url).searchParams);

describe('useUsersByIds', () => {
    it('100 件を超える ID は 100 件ずつに分けて取得し、指定した順に並べる (limit は 100)', async () => {
        const ids = Array.from({ length: 250 }, (_, index) => idOf(index + 1));
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), [LIST_KEY]: idsReply() });
        const { result } = renderHook(() => useUsersByIds([...ids].reverse()), { wrapper: AppTestProvider });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));

        const params = listParams(spy);
        expect(params.map((param) => param.get('ids')?.split(',').length)).toEqual([100, 100, 50]);
        expect(params.every((param) => param.get('limit') === '100')).toBe(true);
        // 送った ID はすべて異なり、重複して送らない
        expect(new Set(params.flatMap((param) => param.get('ids')?.split(',') ?? [])).size).toBe(250);
        expect(result.current.users.size).toBe(250);
        expect(result.current.items.map((user) => user.id)).toEqual([...ids].reverse());
        expect(result.current.missing_ids).toEqual([]);
    });

    it('limit を超えて next_cursor が返った場合は続きを取得する', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: (request) => (new URL(request.url).searchParams.get('cursor') === 'c1'
                ? { status: 200, body: { items: [userOf({ id: OTHER_USER_ID })], next_cursor: null } }
                : { status: 200, body: { items: [userOf({ id: SELF_USER_ID })], next_cursor: 'c1' } }),
        });
        const { result } = renderHook(() => useUsersByIds([SELF_USER_ID, OTHER_USER_ID]), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.items.map((user) => user.id)).toEqual([SELF_USER_ID, OTHER_USER_ID]);
        const [first, second] = listParams(spy);
        expect(second.get('cursor')).toBe('c1');
        expect(second.get('ids')).toBe(first.get('ids'));
    });

    it('見つからない ID・UUID でない ID は missing_ids に入れる (UUID でない ID は送らない。重複は除く)', async () => {
        const unknown = idOf(999);
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [LIST_KEY]: idsReply((id) => id !== unknown) });
        const { result } = renderHook(() => useUsersByIds([OTHER_USER_ID, 'not-a-uuid', unknown, OTHER_USER_ID, '']), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(listParams(spy).map((param) => param.get('ids'))).toEqual([`${OTHER_USER_ID},${unknown}`]);
        expect(result.current.items.map((user) => user.id)).toEqual([OTHER_USER_ID]);
        expect(result.current.missing_ids).toEqual(['not-a-uuid', unknown]);
        expect(result.current.userOf(OTHER_USER_ID)?.display_name).toBe(`user-${OTHER_USER_ID.slice(-4)}`);
        expect(result.current.userOf(unknown)).toBeNull();
    });

    it('ID が空なら API を呼ばずに success', async () => {
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [LIST_KEY]: idsReply() });
        const { result } = renderHook(() => useUsersByIds([]), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.users.size).toBe(0);
        expect(listParams(spy)).toHaveLength(0);
    });

    it('どれか 1 回でも失敗すれば error (一部だけの結果は返さない)', async () => {
        const ids = Array.from({ length: 150 }, (_, index) => idOf(index + 1));
        let calls = 0;
        mockFetch({
            [APP_STATUS_KEY]: appStatusReply(),
            [LIST_KEY]: (request) => {
                calls += 1;
                return calls === 2 ? problemReply(422, 'invalid_user_input') : idsReply()(request);
            },
        });
        const { result } = renderHook(() => useUsersByIds(ids), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'invalid_input', code: 'invalid_user_input' });
        expect(result.current.users.size).toBe(0);
    });

    it('ID の集合が同じなら (順序・配列が変わっても) 取り直さず、集合が変わるか reload で取り直す', async () => {
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [LIST_KEY]: idsReply() });
        const { result, rerender } = renderHook(({ ids }: { ids: string[] }) => useUsersByIds(ids), { wrapper: AppTestProvider, initialProps: { ids: [SELF_USER_ID, OTHER_USER_ID] } });
        await waitFor(() => expect(result.current.status).toBe('success'));
        rerender({ ids: [OTHER_USER_ID, SELF_USER_ID, OTHER_USER_ID] });
        expect(result.current.status).toBe('success');
        expect(result.current.items.map((user) => user.id)).toEqual([OTHER_USER_ID, SELF_USER_ID]);
        expect(listParams(spy)).toHaveLength(1);

        rerender({ ids: [OTHER_USER_ID] });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.reload());
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(listParams(spy).map((param) => param.get('ids'))).toEqual([`${SELF_USER_ID},${OTHER_USER_ID}`, OTHER_USER_ID, OTHER_USER_ID]);
    });
});
