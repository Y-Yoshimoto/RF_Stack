// useTenant のテスト (詳細と ETag の保持)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { mockFetch, problemReply } from '@/shared/testing/fetch_mock';
import { CP_STATUS_KEY, CpTestProvider, cpStatusReply, tenantDetailOf, tenantOf } from '@/control_plane_app/testing/cp_test_support';
import { useTenant } from './useTenant';

const TENANT_ID = '01900000-0000-7000-8000-000000000001';
const DETAIL_KEY = `GET /api/v1/cp/tenants/${TENANT_ID}`;

afterEach(() => {
    vi.restoreAllMocks();
});

describe('useTenant', () => {
    it('詳細と払い出し履歴を取得し、ETag ヘッダーを保持する', async () => {
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [DETAIL_KEY]: { status: 200, body: tenantDetailOf({ version: 3 }), headers: { ETag: '"3"' } } });
        const { result } = renderHook(() => useTenant(TENANT_ID), { wrapper: CpTestProvider });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.etag).toBe('"3"');
        expect(result.current.tenant?.provisioning_history).toHaveLength(1);
    });

    it('ETag ヘッダーが無ければ version から作る', async () => {
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [DETAIL_KEY]: { status: 200, body: tenantDetailOf({ version: 7 }) } });
        const { result } = renderHook(() => useTenant(TENANT_ID), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.etag).toBe('"7"'));
    });

    it('applyUpdate は更新後のテナントと新しい ETag を反映し、履歴は残す。reload で取り直す', async () => {
        let version = 3;
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [DETAIL_KEY]: () => ({ status: 200, body: tenantDetailOf({ version }), headers: { ETag: `"${version}"` } }) });
        const { result } = renderHook(() => useTenant(TENANT_ID), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.applyUpdate({ tenant: tenantOf({ status: 'SUSPENDED', version: 4 }), etag: '"4"' }));
        expect(result.current.tenant?.status).toBe('SUSPENDED');
        expect(result.current.etag).toBe('"4"');
        expect(result.current.tenant?.provisioning_history).toHaveLength(1);

        version = 9;
        act(() => result.current.reload());
        await waitFor(() => expect(result.current.etag).toBe('"9"'));
        expect(result.current.tenant?.status).toBe('ACTIVE');
    });

    it('別のテナントの更新は反映しない', async () => {
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [DETAIL_KEY]: { status: 200, body: tenantDetailOf(), headers: { ETag: '"3"' } } });
        const { result } = renderHook(() => useTenant(TENANT_ID), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.applyUpdate({ tenant: tenantOf({ id: 'other', version: 99 }), etag: '"99"' }));
        expect(result.current.etag).toBe('"3"');
    });

    it('404 は not_found', async () => {
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [DETAIL_KEY]: problemReply(404, 'tenant_not_found') });
        const { result } = renderHook(() => useTenant(TENANT_ID), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'not_found', code: 'tenant_not_found', status: 404 });
        expect(result.current.etag).toBeNull();
    });
});
