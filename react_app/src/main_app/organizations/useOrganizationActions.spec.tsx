// useOrganizationList / useOrganization / useOrganizationActions のテスト (カーソル・ETag の受け渡し・412 / 428 / 403 / 409・member)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, ORGANIZATION_ID, organizationDetailOf, organizationOf, OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { useOrganization, type OrganizationActionUpdate } from './useOrganization';
import { useOrganizationActions, type OrganizationActionResult } from './useOrganizationActions';
import { useOrganizationList } from './useOrganizationList';

const LIST_KEY = 'GET /api/v1/organizations';
const CREATE_KEY = 'POST /api/v1/organizations';
const DETAIL_KEY = `GET /api/v1/organizations/${ORGANIZATION_ID}`;
const PATCH_KEY = `PATCH /api/v1/organizations/${ORGANIZATION_ID}`;
const DELETE_KEY = `DELETE /api/v1/organizations/${ORGANIZATION_ID}`;
const MEMBERS_KEY = `PUT /api/v1/organizations/${ORGANIZATION_ID}/members`;

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 詳細とアクションを同じ画面で使う形で描画する関数 (詳細の取得を待つ)
 * @param {Record<string, MockHandler>} replies API の応答
 * @param {string[]} roles ログイン中のユーザーのロール
 * @returns {Promise<{ result, spy, onUpdated }>} 描画結果・fetch の spy・成功の通知
*/
const renderDetailWithActions = async (replies: Record<string, MockHandler>, roles: string[] = ['tenant_admin']) => {
    const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(roles), [DETAIL_KEY]: { status: 200, body: organizationDetailOf({ version: 3 }), headers: { ETag: '"3"' } }, ...replies });
    const onUpdated = vi.fn();
    const { result } = renderHook(() => {
        const detail = useOrganization(ORGANIZATION_ID);
        const actions = useOrganizationActions({
            onUpdated: (update: OrganizationActionUpdate) => {
                onUpdated(update);
                detail.applyUpdate(update);
            },
        });
        return { detail, actions };
    }, { wrapper: AppTestProvider });
    await waitFor(() => expect(result.current.detail.status).toBe('success'));
    if (roles.includes('tenant_admin')) await waitFor(() => expect(result.current.actions.can_write).toBe(true));
    return { result, spy, onUpdated };
};

const target = (etag: string | null) => ({ organization_id: ORGANIZATION_ID, etag });
const writeKeys = (spy: ReturnType<typeof mockFetch>) => calledKeys(spy).filter((key) => !key.startsWith('GET '));

describe('useOrganizationList', () => {
    it('カーソルで連結し、並び順を 2 ページ目にも付ける', async () => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(['member']),
            [LIST_KEY]: (request) => (new URL(request.url).searchParams.get('cursor') === 'c1'
                ? { status: 200, body: { items: [organizationOf({ id: 'o2', name: '開発部' })], next_cursor: null } }
                : { status: 200, body: { items: [organizationOf({ id: 'o1' })], next_cursor: 'c1' } }),
        });
        const { result } = renderHook(() => useOrganizationList({ sort: '-created_at' }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual(['o1', 'o2']));
        const params = calledRequests(spy).filter((request) => new URL(request.url).pathname === '/api/v1/organizations').map((request) => new URL(request.url).searchParams.toString());
        expect(params).toEqual(['sort=-created_at', 'cursor=c1&sort=-created_at']);
    });
});

describe('useOrganization', () => {
    it('メンバーのユーザー ID と ETag を取得する', async () => {
        const { result } = await renderDetailWithActions({});
        expect(result.current.detail.organization?.member_ids).toEqual([SELF_USER_ID]);
        expect(result.current.detail.etag).toBe('"3"');
    });

    it('削除済み・他テナントは 404 organization_not_found', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [DETAIL_KEY]: problemReply(404, 'organization_not_found') });
        const { result } = renderHook(() => useOrganization(ORGANIZATION_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'not_found', code: 'organization_not_found' });
    });
});

describe('useOrganizationActions: ETag と If-Match', () => {
    it('メンバーの置き換え → 組織名の変更を続けて行い、ETag を引き継ぎ、名前の変更でメンバーを失わない', async () => {
        const { result, spy } = await renderDetailWithActions({
            [MEMBERS_KEY]: { status: 200, body: organizationDetailOf({ version: 4, member_ids: [SELF_USER_ID, OTHER_USER_ID] }), headers: { ETag: '"4"' } },
            [PATCH_KEY]: { status: 200, body: organizationOf({ name: '営業本部', version: 5 }), headers: { ETag: '"5"' } },
        });
        await act(async () => {
            await result.current.actions.setMembers(target(result.current.detail.etag), [SELF_USER_ID, OTHER_USER_ID, OTHER_USER_ID]);
        });
        expect(result.current.detail.organization?.member_ids).toEqual([SELF_USER_ID, OTHER_USER_ID]);
        expect(result.current.detail.etag).toBe('"4"');
        await act(async () => {
            await result.current.actions.update(target(result.current.detail.etag), { name: '営業本部' });
        });
        expect(result.current.detail.organization).toMatchObject({ name: '営業本部', version: 5, member_ids: [SELF_USER_ID, OTHER_USER_ID] });
        expect(result.current.detail.etag).toBe('"5"');

        const sent = calledRequests(spy).filter((request) => request.method !== 'GET');
        expect(sent.map((request) => [request.method, request.headers.get('If-Match'), request.headers.get('X-Requested-With')])).toEqual([['PUT', '"3"', 'rf-stack'], ['PATCH', '"4"', 'rf-stack']]);
        expect(await sent[0].clone().json()).toEqual({ user_ids: [SELF_USER_ID, OTHER_USER_ID] });
        expect(await sent[1].clone().json()).toEqual({ name: '営業本部' });
    });

    it('削除は DELETE に If-Match を付け、204 (本文なし) を成功として通知する', async () => {
        const { result, spy, onUpdated } = await renderDetailWithActions({ [DELETE_KEY]: { status: 204, content_type: 'text/plain' } });
        let outcome: OrganizationActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.remove(target(result.current.detail.etag));
        });
        expect(outcome).toEqual({ ok: true, action: 'delete', organization_id: ORGANIZATION_ID });
        expect(onUpdated).toHaveBeenCalledWith({ action: 'delete', organization_id: ORGANIZATION_ID });
        expect(calledRequests(spy).find((request) => request.method === 'DELETE')?.headers.get('If-Match')).toBe('"3"');
    });

    it('作成は 201 の組織と ETag を通知する', async () => {
        const { result, onUpdated } = await renderDetailWithActions({ [CREATE_KEY]: { status: 201, body: organizationDetailOf({ id: 'new', name: '総務部', version: 1, member_ids: [] }), headers: { ETag: '"1"' } } });
        await act(async () => {
            await result.current.actions.create({ name: '総務部' });
        });
        expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ action: 'create', etag: '"1"', organization: expect.objectContaining({ id: 'new', member_ids: [] }) }));
        // 別の組織の作成は詳細に影響しない
        expect(result.current.detail.organization?.name).toBe('営業部');
    });

    it('412 organization_version_conflict は再取得を促す失敗にし、ETag は変えない。reload で取り直せる', async () => {
        let detail_calls = 0;
        const { result } = await renderDetailWithActions({
            [DETAIL_KEY]: () => {
                detail_calls += 1;
                return { status: 200, body: organizationDetailOf({ version: 2 + detail_calls }), headers: { ETag: `"${2 + detail_calls}"` } };
            },
            [PATCH_KEY]: problemReply(412, 'organization_version_conflict'),
        });
        await act(async () => {
            await result.current.actions.update(target(result.current.detail.etag), { name: 'x' });
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'update', organization_id: ORGANIZATION_ID, kind: 'version_conflict', code: 'organization_version_conflict', requires_reload: true });
        expect(result.current.detail.etag).toBe('"3"');
        act(() => result.current.detail.reload());
        await waitFor(() => expect(result.current.detail.etag).toBe('"4"'));
    });

    it('428 は precondition_required、ETag が無ければ API を呼ばない', async () => {
        const { result, spy } = await renderDetailWithActions({ [MEMBERS_KEY]: problemReply(428, 'precondition_required') });
        await act(async () => {
            await result.current.actions.setMembers(target(result.current.detail.etag), []);
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'set_members', kind: 'precondition_required', status: 428, requires_reload: true });
        await act(async () => {
            await result.current.actions.remove(target(null));
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'delete', kind: 'precondition_required', status: null });
        expect(writeKeys(spy)).toEqual([MEMBERS_KEY]);
    });

    it('409 organization_name_already_exists は conflict', async () => {
        const { result } = await renderDetailWithActions({ [CREATE_KEY]: problemReply(409, 'organization_name_already_exists') });
        await act(async () => {
            await result.current.actions.create({ name: '営業部' });
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'create', organization_id: null, kind: 'conflict', code: 'organization_name_already_exists' });
    });

    it('422 invalid_organization_members の拡張メンバー user_ids を参照できる', async () => {
        const invalid = problemReply(422, 'invalid_organization_members');
        const { result } = await renderDetailWithActions({ [MEMBERS_KEY]: { ...invalid, body: { ...(invalid.body as object), user_ids: ['ghost'] } } });
        await act(async () => {
            await result.current.actions.setMembers(target(result.current.detail.etag), ['ghost']);
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'invalid_input', code: 'invalid_organization_members' });
        expect(result.current.actions.failure?.problem?.user_ids).toEqual(['ghost']);
    });
});

describe('useOrganizationActions: 権限', () => {
    it('member は変更系の API を呼ばずに forbidden', async () => {
        const { result, spy } = await renderDetailWithActions({}, ['member']);
        expect(result.current.actions.can_write).toBe(false);
        await act(async () => {
            await result.current.actions.create({ name: 'x' });
            await result.current.actions.update(target(result.current.detail.etag), { name: 'x' });
            await result.current.actions.setMembers(target(result.current.detail.etag), []);
            await result.current.actions.remove(target(result.current.detail.etag));
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'delete', kind: 'forbidden', status: null });
        expect(writeKeys(spy)).toEqual([]);
    });

    it('API の 403 は forbidden', async () => {
        const { result } = await renderDetailWithActions({ [DELETE_KEY]: problemReply(403, 'forbidden') });
        await act(async () => {
            await result.current.actions.remove(target(result.current.detail.etag));
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'forbidden', status: 403 });
    });
});
