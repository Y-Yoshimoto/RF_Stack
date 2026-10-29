/**
 * @desc コントロールプレーン (CP) の認証状態プロバイダー
 * `/api/auth/cp/status` を読み込み、CP 画面群に認証状態と操作を提供する。
 * 副作用 (状態の読み込み・トップレベル遷移・HTTP リクエスト) はテスト用に差し替えられる。
 */
import { useCallback, type ReactNode } from 'react';
import { AUTH_API } from '@/constants.ts';
import { CP_LOGIN_PATH } from '@/control_plane_app/paths';
import { assignLocation as defaultAssignLocation, logoutAndLeave, toSessionState, type AssignLocation, type Requester } from '@/shared/auth/session';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';
import { requestFetch } from '@/utils/libs/FetchComponents/common';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { ControlPlaneAuthContext, type CpAuthValue } from './context';
import { loadCpSession, startCpLogin, type CpSession } from './session';

export type ControlPlaneAuthProviderProps = {
    children: ReactNode;
    /** セッションの読み込み (既定: `/api/auth/cp/status`)。 */
    loadSession?: () => Promise<CpSession | null>;
    /** トップレベル遷移 (既定: window.location.assign)。 */
    assignLocation?: AssignLocation;
    /** HTTP リクエスト (既定: requestFetch)。ログアウトに使う。 */
    requester?: Requester;
};

export const ControlPlaneAuthProvider = ({ children, loadSession = loadCpSession, assignLocation = defaultAssignLocation, requester = requestFetch }: ControlPlaneAuthProviderProps) => {
    const { result, reload } = useAsyncValue(() => loadSession(), 'cp-session');
    const state = toSessionState(result);

    // 403 (saas_viewer の変更操作など) は操作単位のエラーとして呼び出し元で扱う
    const reportApiError = useCallback((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) reload();
    }, [reload]);

    const login = useCallback(() => startCpLogin(assignLocation), [assignLocation]);

    const logout = useCallback(async () => {
        await logoutAndLeave({ url: AUTH_API.CP_LOGOUT, fallback: CP_LOGIN_PATH, requester, assign: assignLocation });
    }, [requester, assignLocation]);

    const value: CpAuthValue = { state, refresh: reload, login, logout, reportApiError };
    return <ControlPlaneAuthContext value={value}>{children}</ControlPlaneAuthContext>;
};

export default ControlPlaneAuthProvider;
