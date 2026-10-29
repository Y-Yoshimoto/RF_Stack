// プレーン共通の認証処理のテスト
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { fetchAuthStatus, logoutAndLeave, resolveLogoutDestination, toSessionState, type Requester } from './session';
import type { AuthStatusResponse } from './type';

const STATUS: AuthStatusResponse = {
    authenticated: true,
    plane: 'app',
    tenant_code: 'alpha',
    user: { sub: 's', preferred_username: 'alpha-admin', email: null, roles: ['tenant_admin'] },
};

// 固定の値を返す (または例外を送出する) requester
const requesterOf = (result: unknown, is_error = false): Requester => {
    return (async () => {
        if (is_error) throw result;
        return result;
    }) as Requester;
};

describe('fetchAuthStatus', () => {
    it('200 はレスポンスを返す', async () => {
        await expect(fetchAuthStatus('/api/auth/app/status', requesterOf(STATUS))).resolves.toEqual(STATUS);
    });

    it('401 は null (未認証)', async () => {
        await expect(fetchAuthStatus('/x', requesterOf(new ApiError(401, 'Unauthorized'), true))).resolves.toBeNull();
    });

    it('401 以外の失敗は握り潰さずに送出する', async () => {
        const error = new ApiError(503, 'Service Unavailable');
        await expect(fetchAuthStatus('/x', requesterOf(error, true))).rejects.toBe(error);
        await expect(fetchAuthStatus('/x', requesterOf(new TypeError('network'), true))).rejects.toThrow('network');
    });

    it('空の応答は失敗', async () => {
        await expect(fetchAuthStatus('/x', requesterOf(null))).rejects.toThrow();
    });
});

describe('resolveLogoutDestination', () => {
    it('logout_url へ遷移する', () => {
        expect(resolveLogoutDestination({ logout_url: 'http://kc/logout?post_logout_redirect_uri=x' }, '/')).toBe('http://kc/logout?post_logout_redirect_uri=x');
    });

    it('応答が空なら fallback', () => {
        expect(resolveLogoutDestination(null, '/cp/login')).toBe('/cp/login');
    });
});

describe('logoutAndLeave', () => {
    it('POST してから遷移する', async () => {
        const calls: unknown[] = [];
        const requester: Requester = async <T,>(resource_obj: unknown) => {
            calls.push(resource_obj);
            return { logout_url: 'http://kc/logout' } as T;
        };
        const assign = vi.fn();
        await expect(logoutAndLeave({ url: '/api/auth/app/logout', fallback: '/', requester, assign })).resolves.toBe('http://kc/logout');
        expect(calls).toEqual([{ url: '/api/auth/app/logout', method: 'POST' }]);
        expect(assign).toHaveBeenCalledWith('http://kc/logout');
    });

    it('API の失敗は送出し、遷移しない', async () => {
        const assign = vi.fn();
        await expect(logoutAndLeave({ url: '/x', fallback: '/', requester: requesterOf(new ApiError(403, 'Forbidden'), true), assign })).rejects.toBeInstanceOf(ApiError);
        expect(assign).not.toHaveBeenCalled();
    });
});

describe('toSessionState', () => {
    it('結果をセッションの状態に変換する', () => {
        expect(toSessionState({ status: 'loading' })).toEqual({ status: 'loading' });
        expect(toSessionState({ status: 'success', value: null })).toEqual({ status: 'unauthenticated' });
        expect(toSessionState({ status: 'success', value: 1 })).toEqual({ status: 'authenticated', session: 1 });
        expect(toSessionState({ status: 'error', error: 'e' })).toEqual({ status: 'error', error: 'e' });
    });
});
