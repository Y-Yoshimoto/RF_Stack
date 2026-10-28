// useTenantActions のテスト (ETag の受け渡し・412 / 428 / 403・saas_viewer・一時パスワードの扱い)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { CP_STATUS_KEY, CpTestProvider, cpStatusReply, tenantDetailOf, tenantOf } from '@/control_plane_app/testing/cp_test_support';
import type { TenantActionResult, UseTenantActionsOptions } from './useTenantActions';
import { useTenant } from './useTenant';
import { useTenantActions } from './useTenantActions';

const TENANT_ID = '01900000-0000-7000-8000-000000000001';
const DETAIL_KEY = `GET /api/v1/cp/tenants/${TENANT_ID}`;
const SUSPEND_KEY = `POST /api/v1/cp/tenants/${TENANT_ID}/suspend`;
const RESUME_KEY = `POST /api/v1/cp/tenants/${TENANT_ID}/resume`;
const DELETE_KEY = `DELETE /api/v1/cp/tenants/${TENANT_ID}`;
const RETRY_KEY = `POST /api/v1/cp/tenants/${TENANT_ID}/provisioning/retry`;
const CREATE_KEY = 'POST /api/v1/cp/tenants';
const SECRET = 'Tmp-Secret-123!';

const PROVISIONED = {
    status: 201,
    body: { tenant: tenantOf({ version: 1 }), initial_admin: { username: 'admin@acme.example', temporary_password: SECRET }, provisioning_history_id: 'h1' },
    headers: { ETag: '"1"', 'Cache-Control': 'no-store' },
};

afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
});

/**
 * 詳細とアクションを同じ画面で使う形で描画する関数 (認証ステータスの読み込みを待つ)
 * @param {Record<string, MockHandler>} replies API の応答
 * @param {string[]} roles ロール
 * @returns {Promise<{ result, spy }>} 描画結果と fetch の spy
*/
const renderDetailWithActions = async (replies: Record<string, MockHandler>, roles: string[] = ['saas_admin']) => {
    const spy = mockFetch({ [CP_STATUS_KEY]: cpStatusReply(roles), [DETAIL_KEY]: { status: 200, body: tenantDetailOf({ version: 3 }), headers: { ETag: '"3"' } }, ...replies });
    const { result } = renderHook(() => {
        const detail = useTenant(TENANT_ID);
        const actions = useTenantActions({ onUpdated: detail.applyUpdate });
        return { detail, actions };
    }, { wrapper: CpTestProvider });
    await waitFor(() => expect(result.current.detail.status).toBe('success'));
    return { result, spy };
};

/**
 * アクションのみを描画する関数 (権限の読み込みを待つ)
 * @param {Record<string, MockHandler>} replies API の応答
 * @param {UseTenantActionsOptions} options フックのオプション
 * @returns {Promise<{ result, spy }>} 描画結果と fetch の spy
*/
const renderActions = async (replies: Record<string, MockHandler>, options: UseTenantActionsOptions = {}) => {
    const spy = mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), ...replies });
    const { result, unmount } = renderHook(() => useTenantActions(options), { wrapper: CpTestProvider });
    await waitFor(() => expect(result.current.can_write).toBe(true));
    return { result, spy, unmount };
};

describe('useTenantActions: ETag と If-Match', () => {
    it('保持している ETag を If-Match に付け、成功時は新しい ETag を詳細に反映する', async () => {
        const { result, spy } = await renderDetailWithActions({
            [SUSPEND_KEY]: { status: 200, body: tenantOf({ status: 'SUSPENDED', version: 4 }), headers: { ETag: '"4"' } },
            [RESUME_KEY]: { status: 200, body: tenantOf({ status: 'ACTIVE', version: 5 }), headers: { ETag: '"5"' } },
        });
        let outcome: TenantActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.suspend({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
        });
        expect(outcome).toMatchObject({ ok: true, action: 'suspend', etag: '"4"' });
        expect(result.current.detail.etag).toBe('"4"');
        expect(result.current.detail.tenant?.status).toBe('SUSPENDED');

        await act(async () => {
            await result.current.actions.resume({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
        });
        expect(result.current.detail.etag).toBe('"5"');

        const sent = calledRequests(spy).filter((request) => request.method === 'POST');
        expect(sent.map((request) => request.headers.get('If-Match'))).toEqual(['"3"', '"4"']);
        expect(sent.every((request) => request.headers.get('X-Requested-With') === 'rf-stack')).toBe(true);
        expect(result.current.actions.failure).toBeNull();
        expect(result.current.actions.pending).toBeNull();
    });

    it('削除要求は DELETE に If-Match を付ける', async () => {
        const { result, spy } = await renderDetailWithActions({ [DELETE_KEY]: { status: 200, body: tenantOf({ status: 'PENDING_DELETION', version: 4 }), headers: { ETag: '"4"' } } });
        await act(async () => {
            await result.current.actions.requestDeletion({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
        });
        expect(calledRequests(spy).find((request) => request.method === 'DELETE')?.headers.get('If-Match')).toBe('"3"');
        expect(result.current.detail.tenant?.status).toBe('PENDING_DELETION');
    });

    it('412 tenant_version_conflict は再取得を促す失敗にし、ETag は変えない', async () => {
        const { result } = await renderDetailWithActions({ [SUSPEND_KEY]: problemReply(412, 'tenant_version_conflict') });
        let outcome: TenantActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.suspend({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
        });
        expect(outcome?.ok).toBe(false);
        expect(result.current.actions.failure).toMatchObject({ action: 'suspend', tenant_id: TENANT_ID, kind: 'version_conflict', status: 412, code: 'tenant_version_conflict', requires_reload: true });
        expect(result.current.detail.etag).toBe('"3"');
    });

    it('428 は precondition_required (再取得を促す)', async () => {
        const { result } = await renderDetailWithActions({ [RESUME_KEY]: problemReply(428, 'precondition_required') });
        await act(async () => {
            await result.current.actions.resume({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'precondition_required', status: 428, requires_reload: true });
    });

    it('ETag が無い場合は API を呼ばない', async () => {
        const { result, spy } = await renderActions({});
        await act(async () => {
            await result.current.suspend({ tenant_id: TENANT_ID, etag: null });
        });
        expect(result.current.failure).toMatchObject({ kind: 'precondition_required', status: null, requires_reload: true });
        expect(calledKeys(spy)).not.toContain(SUSPEND_KEY);
    });
});

describe('useTenantActions: 権限', () => {
    it('saas_viewer は変更系の API を呼ばずに forbidden', async () => {
        const { result, spy } = await renderDetailWithActions({}, ['saas_viewer']);
        expect(result.current.actions.can_write).toBe(false);
        await act(async () => {
            await result.current.actions.suspend({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
            await result.current.actions.create({ tenant_code: 'x-co', name: 'X', initial_admin: { email: 'a@x.example' } });
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'create', kind: 'forbidden', status: null });
        expect(calledKeys(spy).filter((key) => !key.startsWith('GET '))).toEqual([]);
    });

    it('API の 403 は forbidden', async () => {
        const { result } = await renderDetailWithActions({ [SUSPEND_KEY]: problemReply(403, 'forbidden') });
        await act(async () => {
            await result.current.actions.suspend({ tenant_id: TENANT_ID, etag: result.current.detail.etag });
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'forbidden', status: 403, code: 'forbidden', requires_reload: false });
    });

    it('実行中の二重実行は API を呼ばずに busy', async () => {
        let release: () => void = () => undefined;
        const gate = new Promise<void>((resolve) => { release = resolve; });
        const { result, spy } = await renderActions({});
        spy.mockImplementationOnce(async () => {
            await gate;
            return new Response(JSON.stringify(tenantOf({ version: 4 })), { status: 200, headers: { 'Content-Type': 'application/json', ETag: '"4"' } });
        });
        let first: Promise<TenantActionResult> = Promise.resolve({ ok: false } as TenantActionResult);
        act(() => {
            first = result.current.suspend({ tenant_id: TENANT_ID, etag: '"3"' });
        });
        await waitFor(() => expect(result.current.pending).toBe('suspend'));
        await act(async () => {
            const second = await result.current.resume({ tenant_id: TENANT_ID, etag: '"3"' });
            expect(second).toMatchObject({ ok: false, failure: { kind: 'busy' } });
        });
        await act(async () => {
            release();
            await first;
        });
        expect(result.current.pending).toBeNull();
        expect(calledKeys(spy)).not.toContain(RESUME_KEY);
    });
});

describe('useTenantActions: 作成・再実行と一時パスワード', () => {
    it('作成の一時パスワードは issued_credentials にだけ入り、戻り値・onUpdated・ログには出ない', async () => {
        const log_spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((name) => vi.spyOn(console, name));
        const onUpdated = vi.fn();
        const { result, spy } = await renderActions({ [CREATE_KEY]: PROVISIONED }, { onUpdated });
        let outcome: TenantActionResult | undefined;
        await act(async () => {
            outcome = await result.current.create({ tenant_code: 'acme', name: 'ACME', initial_admin: { email: 'admin@acme.example' } });
        });
        expect(result.current.issued_credentials).toEqual({ username: 'admin@acme.example', temporary_password: SECRET, tenant_id: TENANT_ID, tenant_code: 'acme' });
        expect(outcome).toMatchObject({ ok: true, action: 'create', etag: '"1"' });
        expect(JSON.stringify(outcome)).not.toContain(SECRET);
        expect(JSON.stringify(onUpdated.mock.calls)).not.toContain(SECRET);
        expect(JSON.stringify(log_spies.map((log) => log.mock.calls))).not.toContain(SECRET);
        expect(await calledRequests(spy).find((request) => request.method === 'POST')?.clone().json()).toEqual({ tenant_code: 'acme', name: 'ACME', initial_admin: { email: 'admin@acme.example' } });

        act(() => result.current.dismissCredentials());
        expect(result.current.issued_credentials).toBeNull();
    });

    it('一時パスワードは次の操作の開始で消える', async () => {
        const { result } = await renderActions({ [CREATE_KEY]: PROVISIONED, [SUSPEND_KEY]: problemReply(409, 'invalid_tenant_transition') });
        await act(async () => {
            await result.current.create({ tenant_code: 'acme', name: 'ACME', initial_admin: { email: 'admin@acme.example' } });
        });
        expect(result.current.issued_credentials).not.toBeNull();
        await act(async () => {
            await result.current.suspend({ tenant_id: TENANT_ID, etag: '"1"' });
        });
        expect(result.current.issued_credentials).toBeNull();
        expect(result.current.failure).toMatchObject({ kind: 'conflict', code: 'invalid_tenant_transition', requires_reload: true });
    });

    it('一時パスワードは保持時間を過ぎると消える', async () => {
        const { result } = await renderActions({ [CREATE_KEY]: PROVISIONED }, { credentials_ttl_ms: 50 });
        await act(async () => {
            await result.current.create({ tenant_code: 'acme', name: 'ACME', initial_admin: { email: 'admin@acme.example' } });
        });
        expect(result.current.issued_credentials?.temporary_password).toBe(SECRET);
        await waitFor(() => expect(result.current.issued_credentials).toBeNull());
    });

    it('払い出しの失敗 (502) は external_failure で、problem の tenant_id を参照できる', async () => {
        const failed = problemReply(502, 'tenant_provisioning_failed');
        const { result } = await renderActions({ [CREATE_KEY]: { ...failed, body: { ...(failed.body as object), tenant_id: TENANT_ID, step: 'create_realm' } } });
        await act(async () => {
            await result.current.create({ tenant_code: 'acme', name: 'ACME', initial_admin: { email: 'admin@acme.example' } });
        });
        expect(result.current.failure).toMatchObject({ action: 'create', kind: 'external_failure', code: 'tenant_provisioning_failed' });
        expect(result.current.failure?.problem?.tenant_id).toBe(TENANT_ID);
        expect(result.current.issued_credentials).toBeNull();
    });

    it('再実行は initial_admin を本文で渡し、ETag があれば If-Match に付ける', async () => {
        const { result, spy } = await renderActions({ [RETRY_KEY]: { ...PROVISIONED, status: 200 } });
        const initial_admin = { email: 'admin@acme.example', username: 'admin' };
        await act(async () => {
            await result.current.retry({ tenant_id: TENANT_ID, etag: '"2"' }, initial_admin);
        });
        const request = calledRequests(spy).find((item) => item.method === 'POST');
        expect(await request?.clone().json()).toEqual({ initial_admin });
        expect(request?.headers.get('If-Match')).toBe('"2"');
        expect(result.current.issued_credentials?.temporary_password).toBe(SECRET);
    });

    it('再実行は ETag が無くても実行できる (If-Match は任意)', async () => {
        const { result, spy } = await renderActions({ [RETRY_KEY]: { ...PROVISIONED, status: 200 } });
        await act(async () => {
            await result.current.retry({ tenant_id: TENANT_ID, etag: null }, { email: 'admin@acme.example' });
        });
        expect(calledRequests(spy).find((item) => item.method === 'POST')?.headers.get('If-Match')).toBeNull();
        expect(result.current.failure).toBeNull();
    });
});
