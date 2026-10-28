/**
 * @desc アプリケーションプレーン (AP) の認証状態プロバイダー
 * `/api/auth/app/status` を読み込み、AP 画面群に認証状態と操作 (ログイン・ログアウト・API エラーの反映) を提供する。
 * 副作用 (状態の読み込み・トップレベル遷移・HTTP リクエスト) はテスト用に差し替えられる。
 */
import { useCallback, useState, type ReactNode } from 'react';
import { AUTH_API } from '@/constants.ts';
import { classifyAppApiError } from '@/main_app/api/errors';
import { appLoginPath, LANDING_PATH } from '@/main_app/paths';
import { assignLocation as defaultAssignLocation, logoutAndLeave, toSessionState, type AssignLocation, type Requester } from '@/shared/auth/session';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';
import { requestFetch } from '@/utils/libs/FetchComponents/common';
import { AppAuthContext, type AppAuthValue } from './context';
import type { TenantBlockReason } from './guard';
import { loadAppSession, startAppLogin, type AppSession } from './session';

export type AppAuthProviderProps = {
    children: ReactNode;
    /** セッションの読み込み (既定: `/api/auth/app/status`)。 */
    loadSession?: () => Promise<AppSession | null>;
    /** トップレベル遷移 (既定: window.location.assign)。 */
    assignLocation?: AssignLocation;
    /** HTTP リクエスト (既定: requestFetch)。ログアウトに使う。 */
    requester?: Requester;
};

export const AppAuthProvider = ({ children, loadSession = loadAppSession, assignLocation = defaultAssignLocation, requester = requestFetch }: AppAuthProviderProps) => {
    const { result, reload } = useAsyncValue(() => loadSession(), 'app-session');
    const [blocked, setBlocked] = useState<TenantBlockReason | null>(null);
    const state = toSessionState(result);
    const session_tenant_code = state.status === 'authenticated' ? state.session.tenant_code : null;

    const refresh = useCallback(() => {
        setBlocked(null);
        reload();
    }, [reload]);

    const reportApiError = useCallback((error: unknown) => {
        const effect = classifyAppApiError(error);
        if (effect === 'unauthenticated') refresh();
        else if (effect === 'tenant_suspended') setBlocked('suspended');
        else if (effect === 'tenant_unavailable') setBlocked('unavailable');
    }, [refresh]);

    const login = useCallback((tenant_code: string) => startAppLogin(tenant_code, assignLocation), [assignLocation]);

    const logout = useCallback(async () => {
        // 応答に遷移先が無い場合は、ログイン中のテナントのログイン画面 (テナント不明ならランディング)
        const fallback = session_tenant_code ? appLoginPath(session_tenant_code) : LANDING_PATH;
        await logoutAndLeave({ url: AUTH_API.APP_LOGOUT, fallback, requester, assign: assignLocation });
    }, [session_tenant_code, requester, assignLocation]);

    const value: AppAuthValue = { state, blocked, refresh, login, logout, reportApiError };
    return <AppAuthContext value={value}>{children}</AppAuthContext>;
};

export default AppAuthProvider;
