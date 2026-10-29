// AP の認証状態フック (AppAuthProvider / useAppAuth / useAppApiClient) のテスト
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useAppApiClient } from '@/main_app/api/client';
import { mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { AppAuthProvider } from './AppAuthProvider';
import { loadAppSession } from './session';
import { useAppAuth } from './useAppAuth';

const STATUS = { authenticated: true, plane: 'app', tenant_code: 'alpha', user: { sub: 's', preferred_username: 'alpha-admin', email: null, roles: ['tenant_admin'] } };

afterEach(() => {
    vi.restoreAllMocks();
});

const wrapperOf = (assign: (url: string) => void) => ({ children }: { children: ReactNode }) => <AppAuthProvider assignLocation={assign}>{children}</AppAuthProvider>;

describe('loadAppSession', () => {
    it('200 は tenant_code を持つセッション、401 は null', async () => {
        mockFetch({ 'GET /api/auth/app/status': { status: 200, body: STATUS } });
        await expect(loadAppSession()).resolves.toEqual({ tenant_code: 'alpha', user: STATUS.user });
        vi.restoreAllMocks();
        mockFetch({ 'GET /api/auth/app/status': problemReply(401, 'unauthenticated') });
        await expect(loadAppSession()).resolves.toBeNull();
    });

    it('tenant_code が無い応答は契約違反として失敗', async () => {
        mockFetch({ 'GET /api/auth/app/status': { status: 200, body: { ...STATUS, tenant_code: null } } });
        await expect(loadAppSession()).rejects.toThrow();
    });
});

describe('AppAuthProvider', () => {
    it('状態 API の結果を state に反映する', async () => {
        mockFetch({ 'GET /api/auth/app/status': { status: 200, body: STATUS } });
        const { result } = renderHook(() => useAppAuth(), { wrapper: wrapperOf(vi.fn()) });
        expect(result.current.state.status).toBe('loading');
        await waitFor(() => expect(result.current.state).toEqual({ status: 'authenticated', session: { tenant_code: 'alpha', user: STATUS.user } }));
    });

    it('401 以外の失敗は error (未認証にしない)', async () => {
        mockFetch({ 'GET /api/auth/app/status': problemReply(503, 'service_unavailable') });
        const { result } = renderHook(() => useAppAuth(), { wrapper: wrapperOf(vi.fn()) });
        await waitFor(() => expect(result.current.state.status).toBe('error'));
    });

    it('login はテナントコード付きのログイン開始 API へ遷移する', async () => {
        mockFetch({ 'GET /api/auth/app/status': problemReply(401, 'unauthenticated') });
        const assign = vi.fn();
        const { result } = renderHook(() => useAppAuth(), { wrapper: wrapperOf(assign) });
        await waitFor(() => expect(result.current.state.status).toBe('unauthenticated'));
        act(() => result.current.login('alpha'));
        expect(assign).toHaveBeenCalledWith('/api/auth/app/login?tenant_code=alpha');
    });

    it('logout は CSRF 対策ヘッダー付きで POST し、logout_url へ遷移する', async () => {
        const spy = mockFetch({
            'GET /api/auth/app/status': { status: 200, body: STATUS },
            'POST /api/auth/app/logout': { status: 200, body: { logout_url: 'http://kc/logout' } },
        });
        const assign = vi.fn();
        const { result } = renderHook(() => useAppAuth(), { wrapper: wrapperOf(assign) });
        await waitFor(() => expect(result.current.state.status).toBe('authenticated'));
        await act(() => result.current.logout());
        const request = spy.mock.calls.map(([input]) => input).find((input): input is Request => input instanceof Request && input.method === 'POST');
        expect(request?.headers.get('X-Requested-With')).toBe('rf-stack');
        expect(assign).toHaveBeenCalledWith('http://kc/logout');
    });

    it('logout の失敗は reject し、遷移しない', async () => {
        mockFetch({
            'GET /api/auth/app/status': { status: 200, body: STATUS },
            'POST /api/auth/app/logout': problemReply(403, 'csrf_validation_failed'),
        });
        const assign = vi.fn();
        const { result } = renderHook(() => useAppAuth(), { wrapper: wrapperOf(assign) });
        await waitFor(() => expect(result.current.state.status).toBe('authenticated'));
        await expect(result.current.logout()).rejects.toBeInstanceOf(ApiError);
        expect(assign).not.toHaveBeenCalled();
    });

    it('API クライアントの 403 tenant_inactive は blocked=suspended、401 は状態を再取得する', async () => {
        let status_reply: MockReply = { status: 200, body: STATUS };
        const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
            const url = new URL(input instanceof Request ? input.url : String(input)).pathname;
            if (url === '/api/auth/app/status') return new Response(JSON.stringify(status_reply.body), { status: status_reply.status, headers: { 'Content-Type': status_reply.status === 200 ? 'application/json' : 'application/problem+json' } });
            const reply = url === '/api/v1/me' ? problemReply(403, 'tenant_inactive') : problemReply(401, 'unauthenticated');
            return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { 'Content-Type': 'application/problem+json' } });
        });
        const { result } = renderHook(() => ({ auth: useAppAuth(), client: useAppApiClient() }), { wrapper: wrapperOf(vi.fn()) });
        await waitFor(() => expect(result.current.auth.state.status).toBe('authenticated'));

        await act(() => expect(result.current.client.request({ url: '/api/v1/me' })).rejects.toBeInstanceOf(ApiError));
        expect(result.current.auth.blocked).toBe('suspended');

        status_reply = problemReply(401, 'unauthenticated');
        await act(() => expect(result.current.client.request({ url: '/api/v1/other' })).rejects.toBeInstanceOf(ApiError));
        await waitFor(() => expect(result.current.auth.state.status).toBe('unauthenticated'));
        expect(result.current.auth.blocked).toBeNull();
        expect(spy).toHaveBeenCalled();
    });

    it('プロバイダーの外で useAppAuth を使うと例外', () => {
        vi.spyOn(console, 'error').mockImplementation(() => { });
        expect(() => renderHook(() => useAppAuth())).toThrow();
    });
});
