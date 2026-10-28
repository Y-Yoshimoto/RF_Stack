// useUser / useUserActions のテスト (ETag の受け渡し・ロールの取り直し・412 / 428 / 403 / 409・member・自分自身・一時パスワード)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, OTHER_USER_ID, SELF_USER_ID, userDetailOf, userOf } from '@/main_app/testing/app_test_support';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { useUser } from './useUser';
import { useUserActions, type UseUserActionsOptions, type UserActionResult } from './useUserActions';

const DETAIL_KEY = `GET /api/v1/users/${OTHER_USER_ID}`;
const PATCH_KEY = `PATCH /api/v1/users/${OTHER_USER_ID}`;
const SELF_PATCH_KEY = `PATCH /api/v1/users/${SELF_USER_ID}`;
const CREATE_KEY = 'POST /api/v1/users';
const SECRET = 'Tmp-Secret-456!';

const CREATED = {
    status: 201,
    body: { user: userDetailOf({ id: OTHER_USER_ID, version: 1, roles: ['member'] }), credentials: { username: 'taro', temporary_password: SECRET } },
    headers: { ETag: '"1"', 'Cache-Control': 'no-store' },
};
const NEW_USER = { email: 'taro@alpha.example', first_name: 'Taro', last_name: 'Yamada' };

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 詳細とアクションを同じ画面で使う形で描画する関数 (詳細の取得を待つ)
 * @param {Record<string, MockHandler>} replies API の応答
 * @param {string[]} roles ログイン中のユーザーのロール
 * @returns {Promise<{ result, spy }>} 描画結果と fetch の spy
*/
const renderDetailWithActions = async (replies: Record<string, MockHandler>, roles: string[] = ['tenant_admin']) => {
    const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(roles), [DETAIL_KEY]: { status: 200, body: userDetailOf({ version: 3 }), headers: { ETag: '"3"' } }, ...replies });
    const { result } = renderHook(() => {
        const detail = useUser(OTHER_USER_ID);
        const actions = useUserActions({ self_user_id: SELF_USER_ID, onUpdated: detail.applyUpdate });
        return { detail, actions };
    }, { wrapper: AppTestProvider });
    await waitFor(() => expect(result.current.detail.status).toBe('success'));
    return { result, spy };
};

/**
 * アクションのみを描画する関数 (権限の読み込みを待つ)
 * @param {Record<string, MockHandler>} replies API の応答
 * @param {Partial<UseUserActionsOptions>} options フックのオプション
 * @returns {Promise<{ result, spy, unmount }>} 描画結果と fetch の spy
*/
const renderActions = async (replies: Record<string, MockHandler>, options: Partial<UseUserActionsOptions> = {}) => {
    const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(), ...replies });
    const { result, unmount } = renderHook(() => useUserActions({ self_user_id: SELF_USER_ID, ...options }), { wrapper: AppTestProvider });
    await waitFor(() => expect(result.current.can_write).toBe(true));
    return { result, spy, unmount };
};

const writeKeys = (spy: ReturnType<typeof mockFetch>) => calledKeys(spy).filter((key) => !key.startsWith('GET '));

describe('useUser', () => {
    it('詳細 (ロールを含む) と ETag を取得する。ETag ヘッダーが無ければ version から作る', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [DETAIL_KEY]: { status: 200, body: userDetailOf({ version: 5, roles: ['tenant_admin'] }) } });
        const { result } = renderHook(() => useUser(OTHER_USER_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.user?.roles).toEqual(['tenant_admin']);
        expect(result.current.etag).toBe('"5"');
    });

    it('404 user_not_found は not_found', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [DETAIL_KEY]: problemReply(404, 'user_not_found') });
        const { result } = renderHook(() => useUser(OTHER_USER_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'not_found', code: 'user_not_found' });
    });
});

describe('useUserActions: ETag と If-Match', () => {
    it('保持している ETag を If-Match に付け、送った項目だけを PATCH し、成功時は新しい ETag とロール以外を詳細に反映する', async () => {
        const { result, spy } = await renderDetailWithActions({
            [PATCH_KEY]: { status: 200, body: userOf({ display_name: '太郎 山田', version: 4 }), headers: { ETag: '"4"' } },
        });
        let outcome: UserActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.update({ user_id: OTHER_USER_ID, etag: result.current.detail.etag }, { name: { first_name: '太郎', last_name: '山田' } });
        });
        expect(outcome).toMatchObject({ ok: true, action: 'update', etag: '"4"', roles_stale: false });
        expect(result.current.detail.etag).toBe('"4"');
        expect(result.current.detail.user).toMatchObject({ display_name: '太郎 山田', version: 4, roles: ['member'] });

        const request = calledRequests(spy).find((item) => item.method === 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(request?.headers.get('X-Requested-With')).toBe('rf-stack');
        expect(await request?.clone().json()).toEqual({ first_name: '太郎', last_name: '山田' });
        expect(calledKeys(spy).filter((key) => key === DETAIL_KEY)).toHaveLength(1);
    });

    it('ロールを変えた更新は、応答にロールが無いため詳細を取り直す', async () => {
        let detail_calls = 0;
        const { result, spy } = await renderDetailWithActions({
            [DETAIL_KEY]: () => {
                detail_calls += 1;
                return detail_calls === 1
                    ? { status: 200, body: userDetailOf({ version: 3 }), headers: { ETag: '"3"' } }
                    : { status: 200, body: userDetailOf({ version: 4, roles: ['tenant_admin', 'member'] }), headers: { ETag: '"4"' } };
            },
            [PATCH_KEY]: { status: 200, body: userOf({ version: 4 }), headers: { ETag: '"4"' } },
        });
        await act(async () => {
            await result.current.actions.update({ user_id: OTHER_USER_ID, etag: result.current.detail.etag }, { roles: ['tenant_admin', 'member'] });
        });
        await waitFor(() => expect(result.current.detail.user?.roles).toEqual(['tenant_admin', 'member']));
        expect(result.current.detail.etag).toBe('"4"');
        expect(calledKeys(spy).filter((key) => key === DETAIL_KEY)).toHaveLength(2);
        expect(await calledRequests(spy).find((item) => item.method === 'PATCH')?.clone().json()).toEqual({ roles: ['tenant_admin', 'member'] });
    });

    it('412 user_version_conflict は再取得を促す失敗にし、ETag は変えない', async () => {
        const { result } = await renderDetailWithActions({ [PATCH_KEY]: problemReply(412, 'user_version_conflict') });
        let outcome: UserActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.update({ user_id: OTHER_USER_ID, etag: result.current.detail.etag }, { is_active: false });
        });
        expect(outcome?.ok).toBe(false);
        expect(result.current.actions.failure).toMatchObject({ action: 'update', user_id: OTHER_USER_ID, kind: 'version_conflict', status: 412, code: 'user_version_conflict', requires_reload: true });
        expect(result.current.detail.etag).toBe('"3"');
    });

    it('428 は precondition_required (再取得を促す)', async () => {
        const { result } = await renderDetailWithActions({ [PATCH_KEY]: problemReply(428, 'precondition_required') });
        await act(async () => {
            await result.current.actions.update({ user_id: OTHER_USER_ID, etag: result.current.detail.etag }, { is_active: true });
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'precondition_required', status: 428, requires_reload: true });
    });

    it('ETag が無い・変更が無い場合は API を呼ばない', async () => {
        const { result, spy } = await renderActions({});
        await act(async () => {
            await result.current.update({ user_id: OTHER_USER_ID, etag: null }, { is_active: false });
        });
        expect(result.current.failure).toMatchObject({ kind: 'precondition_required', status: null, requires_reload: true });
        await act(async () => {
            await result.current.update({ user_id: OTHER_USER_ID, etag: '"3"' }, {});
        });
        expect(result.current.failure).toMatchObject({ kind: 'invalid_input', status: null });
        expect(writeKeys(spy)).toEqual([]);
    });
});

describe('useUserActions: 権限と自分自身', () => {
    it('member は変更系の API を呼ばずに forbidden', async () => {
        const { result, spy } = await renderDetailWithActions({}, ['member']);
        expect(result.current.actions.can_write).toBe(false);
        await act(async () => {
            await result.current.actions.update({ user_id: OTHER_USER_ID, etag: result.current.detail.etag }, { is_active: false });
            await result.current.actions.create(NEW_USER);
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'create', kind: 'forbidden', status: null });
        expect(writeKeys(spy)).toEqual([]);
    });

    it('API の 403 は forbidden', async () => {
        const { result } = await renderDetailWithActions({ [PATCH_KEY]: problemReply(403, 'forbidden') });
        await act(async () => {
            await result.current.actions.update({ user_id: OTHER_USER_ID, etag: result.current.detail.etag }, { is_active: false });
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'forbidden', status: 403, requires_reload: false });
    });

    it('自分自身の無効化・tenant_admin の解除は API を呼ばずに conflict (code は API と同じ)', async () => {
        const { result, spy } = await renderActions({});
        let outcome: UserActionResult | undefined;
        await act(async () => {
            outcome = await result.current.update({ user_id: SELF_USER_ID, etag: '"3"' }, { is_active: false });
        });
        expect(outcome).toMatchObject({ ok: false, failure: { action: 'update', user_id: SELF_USER_ID, kind: 'conflict', status: null, code: 'user_self_modification_forbidden' } });
        await act(async () => {
            await result.current.update({ user_id: SELF_USER_ID, etag: '"3"' }, { roles: ['member'] });
        });
        expect(result.current.failure).toMatchObject({ kind: 'conflict', code: 'user_self_modification_forbidden' });
        expect(writeKeys(spy)).toEqual([]);
    });

    it('自分自身でも禁止されていない変更 (姓名) は API を呼ぶ', async () => {
        const { result, spy } = await renderActions({ [SELF_PATCH_KEY]: { status: 200, body: userOf({ id: SELF_USER_ID, version: 4 }), headers: { ETag: '"4"' } } });
        await act(async () => {
            await result.current.update({ user_id: SELF_USER_ID, etag: '"3"' }, { name: { first_name: 'a', last_name: 'b' }, roles: ['tenant_admin'] });
        });
        expect(result.current.failure).toBeNull();
        expect(writeKeys(spy)).toEqual([SELF_PATCH_KEY]);
    });

    it('自分の ID が未取得なら API に任せ、409 user_self_modification_forbidden を conflict にする', async () => {
        const conflict = problemReply(409, 'user_self_modification_forbidden');
        const { result, spy } = await renderActions({ [SELF_PATCH_KEY]: { ...conflict, body: { ...(conflict.body as object), operation: 'deactivate' } } }, { self_user_id: null });
        await act(async () => {
            await result.current.update({ user_id: SELF_USER_ID, etag: '"3"' }, { is_active: false });
        });
        expect(writeKeys(spy)).toEqual([SELF_PATCH_KEY]);
        expect(result.current.failure).toMatchObject({ kind: 'conflict', status: 409, code: 'user_self_modification_forbidden', requires_reload: false });
        expect(result.current.failure?.problem?.operation).toBe('deactivate');
    });
});

describe('useUserActions: 作成と一時パスワード', () => {
    it('一時パスワードは issued_credentials にだけ入り、戻り値・onUpdated・ログには出ない', async () => {
        const log_spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((name) => vi.spyOn(console, name));
        const onUpdated = vi.fn();
        const { result, spy } = await renderActions({ [CREATE_KEY]: CREATED }, { onUpdated });
        let outcome: UserActionResult | undefined;
        await act(async () => {
            outcome = await result.current.create({ ...NEW_USER, roles: ['member'] });
        });
        expect(result.current.issued_credentials).toEqual({ username: 'taro', temporary_password: SECRET, user_id: OTHER_USER_ID, display_name: 'Taro Yamada' });
        expect(outcome).toMatchObject({ ok: true, action: 'create', etag: '"1"' });
        expect(JSON.stringify(outcome)).not.toContain(SECRET);
        expect(onUpdated).toHaveBeenCalledTimes(1);
        expect(JSON.stringify(onUpdated.mock.calls)).not.toContain(SECRET);
        expect(JSON.stringify(log_spies.map((log) => log.mock.calls))).not.toContain(SECRET);
        const request = calledRequests(spy).find((item) => item.method === 'POST');
        expect(await request?.clone().json()).toEqual({ ...NEW_USER, roles: ['member'] });
        expect(request?.headers.get('X-Requested-With')).toBe('rf-stack');

        act(() => result.current.dismissCredentials());
        expect(result.current.issued_credentials).toBeNull();
    });

    it('一時パスワードは次の操作の開始で消える (弾かれた操作でも消える)', async () => {
        const { result } = await renderActions({ [CREATE_KEY]: CREATED });
        await act(async () => {
            await result.current.create(NEW_USER);
        });
        expect(result.current.issued_credentials).not.toBeNull();
        await act(async () => {
            await result.current.update({ user_id: OTHER_USER_ID, etag: null }, { is_active: false });
        });
        expect(result.current.issued_credentials).toBeNull();
    });

    it('一時パスワードは保持時間を過ぎると消える', async () => {
        const { result } = await renderActions({ [CREATE_KEY]: CREATED }, { credentials_ttl_ms: 50 });
        await act(async () => {
            await result.current.create(NEW_USER);
        });
        expect(result.current.issued_credentials?.temporary_password).toBe(SECRET);
        await waitFor(() => expect(result.current.issued_credentials).toBeNull());
    });

    it('アンマウントすると一時パスワードは残らない (再表示しても null)', async () => {
        const { result, unmount } = await renderActions({ [CREATE_KEY]: CREATED });
        await act(async () => {
            await result.current.create(NEW_USER);
        });
        expect(result.current.issued_credentials).not.toBeNull();
        unmount();
        const { result: again } = renderHook(() => useUserActions({ self_user_id: SELF_USER_ID }), { wrapper: AppTestProvider });
        expect(again.current.issued_credentials).toBeNull();
    });

    it('重複 (409 user_already_exists)・IdP の失敗 (502) は一時パスワードを持たない失敗', async () => {
        const { result } = await renderActions({ [CREATE_KEY]: problemReply(502, 'identity_provider_operation_failed') });
        await act(async () => {
            await result.current.create(NEW_USER);
        });
        expect(result.current.failure).toMatchObject({ action: 'create', user_id: null, kind: 'external_failure', code: 'identity_provider_operation_failed' });
        expect(result.current.issued_credentials).toBeNull();
    });

    it('実行中の二重実行は API を呼ばずに busy', async () => {
        let release: () => void = () => undefined;
        const gate = new Promise<void>((resolve) => { release = resolve; });
        const { result, spy } = await renderActions({});
        spy.mockImplementationOnce(async () => {
            await gate;
            return new Response(JSON.stringify(userOf({ version: 4 })), { status: 200, headers: { 'Content-Type': 'application/json', ETag: '"4"' } });
        });
        let first: Promise<UserActionResult> = Promise.resolve({ ok: false } as UserActionResult);
        act(() => {
            first = result.current.update({ user_id: OTHER_USER_ID, etag: '"3"' }, { is_active: false });
        });
        await waitFor(() => expect(result.current.pending).toBe('update'));
        await act(async () => {
            const second = await result.current.create(NEW_USER);
            expect(second).toMatchObject({ ok: false, failure: { kind: 'busy' } });
        });
        await act(async () => {
            release();
            await first;
        });
        expect(result.current.pending).toBeNull();
        expect(calledKeys(spy)).not.toContain(CREATE_KEY);
    });
});
