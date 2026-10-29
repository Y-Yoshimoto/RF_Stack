// useMe と、AP の API の 401 (user_deactivated / session_expired) が認証状態の取り直しに乗ることのテスト
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useAppAuth, useAppPermissions } from '@/main_app/auth/useAppAuth';
import type { MeRead } from '@/main_app/api/contract';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, ORGANIZATION_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { useUserList } from '@/main_app/users/useUserList';
import { calledKeys, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { myOrganizationsOf, useMe } from './useMe';

const ME_KEY = 'GET /api/v1/me';
const SECOND_ORGANIZATION_ID = '01900000-0000-7000-8000-00000000b002';
const ME: MeRead = {
    tenant: { id: '01900000-0000-7000-8000-0000000000t1', tenant_code: 'alpha' },
    user: { id: SELF_USER_ID, username: 'alpha-admin', email: null, roles: ['tenant_admin', 'member'] },
    organizations: [{ id: SECOND_ORGANIZATION_ID, name: '開発部' }, { id: ORGANIZATION_ID, name: '営業部' }],
};

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 1 回目は認証済み、2 回目以降は 401 を返す状態 API の応答を作る関数 (サーバーがセッションを削除した後を表す)
 * @returns {() => MockReply} 応答関数
*/
const statusThenExpired = () => {
    let calls = 0;
    return (): MockReply => {
        calls += 1;
        return calls === 1 ? appStatusReply() : problemReply(401, 'session_expired');
    };
};

describe('useMe', () => {
    it('テナントとユーザーを取得し、user.id (AP のユーザー ID) を self_user_id にする', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [ME_KEY]: { status: 200, body: ME } });
        const { result } = renderHook(() => useMe(), { wrapper: AppTestProvider });
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.me).toEqual(ME);
        expect(result.current.self_user_id).toBe(SELF_USER_ID);
    });

    it('所属組織 (organizations) を応答の順 (組織名順) のまま返し、組織の API は呼ばない', async () => {
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), [ME_KEY]: { status: 200, body: ME } });
        const { result } = renderHook(() => useMe(), { wrapper: AppTestProvider });
        expect(result.current.organizations).toEqual([]);
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.organizations).toEqual([{ id: SECOND_ORGANIZATION_ID, name: '開発部' }, { id: ORGANIZATION_ID, name: '営業部' }]);
        expect(myOrganizationsOf(result.current)).toMatchObject({ status: 'success', organizations: ME.organizations, error: null });
        expect(calledKeys(spy).filter((key) => key.includes('/organizations'))).toEqual([]);
    });

    it('所属が無ければ空の配列。取得の失敗は myOrganizationsOf でも error', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [ME_KEY]: { status: 200, body: { ...ME, organizations: [] } } });
        const { result } = renderHook(() => useMe(), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(myOrganizationsOf(result.current).organizations).toEqual([]);

        vi.restoreAllMocks();
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [ME_KEY]: problemReply(502, 'identity_provider_operation_failed') });
        const { result: failed } = renderHook(() => useMe(), { wrapper: AppTestProvider });
        await waitFor(() => expect(failed.current.status).toBe('error'));
        expect(myOrganizationsOf(failed.current)).toMatchObject({ status: 'error', organizations: [], error: { kind: 'external_failure' } });
    });

    it('403 tenant_inactive はテナントの利用不可として認証状態に反映する', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [ME_KEY]: problemReply(403, 'tenant_inactive') });
        const { result } = renderHook(() => ({ me: useMe(), auth: useAppAuth() }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.me.status).toBe('error'));
        expect(result.current.me.error).toMatchObject({ kind: 'forbidden', code: 'tenant_inactive' });
        expect(result.current.auth.blocked).toBe('suspended');
    });
});

describe('AP の API の 401', () => {
    it.each(['user_deactivated', 'session_expired'])('%s は状態 API を取り直し、未認証 (ログイン画面へ) にする', async (code) => {
        const spy = mockFetch({ [APP_STATUS_KEY]: statusThenExpired(), [ME_KEY]: problemReply(401, code), 'GET /api/v1/users': problemReply(401, code) });
        const { result } = renderHook(() => ({ me: useMe(), users: useUserList(), auth: useAppAuth(), permissions: useAppPermissions() }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.auth.state.status).toBe('unauthenticated'));
        expect(result.current.me.error).toMatchObject({ kind: 'unauthenticated', status: 401, code });
        expect(result.current.users.error).toMatchObject({ kind: 'unauthenticated' });
        expect(result.current.permissions.can_write).toBe(false);
        expect(calledKeys(spy).filter((key) => key === APP_STATUS_KEY).length).toBeGreaterThanOrEqual(2);
    });
});
