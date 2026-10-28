// 認証, 認可情報を管理するカスタムフック
import { useEffect, useState } from 'react';
import { useSessionStorage } from 'react-use';
// 定数のインポート
import { AUTH_API, STORAGE_KEY } from '@/constants.ts';

// httpリクスト関連
import { requestFetch } from '@/utils/libs/FetchComponents/';
import { ResourceObj } from '@/utils/libs/FetchComponents';
import type {
    AuthNInfo,
    AuthStatusResponse,
    AuthUserInfo,
    AuthZInfo,
    Status,
    UseAuthNZReturn,
} from './type';
/**
 * 状態 API のレスポンスからユーザー情報を組み立てる関数
 * @param {AuthStatusResponse} response 状態 API のレスポンス
 * @returns {AuthUserInfo | undefined} ユーザー情報 (テナントコードを含む)
*/
const toUserInfo = (response: AuthStatusResponse): AuthUserInfo | undefined => {
    if (!response.authenticated || !response.user) return undefined;
    return { ...response.user, tenant_code: response.tenant_code };
};

// デフォルト値の設定 ////////////////////////////////////////////////////////////
const default_auth_n_info: AuthNInfo = {
    is_auth_n: undefined,
    setIsAuthN: () => { },
    user_info: undefined,
    setUserInfo: () => { },
};
const default_auth_z_info: AuthZInfo = {
    is_auth_z: undefined,
    setIsAuthZ: () => { },
    roles: undefined,
    setRoles: () => { },
    permissions: undefined,
    setPermissions: () => { },
};
const default_status: Status = {
    is_auth_n: undefined,
    is_auth_z: undefined,
};
export const default_return_value: UseAuthNZReturn = {
    auth_n_info: default_auth_n_info,
    auth_z_info: default_auth_z_info,
    user_info: default_auth_n_info.user_info,
    auth_status: default_status,
    command: {
        login: () => { },
        logout: () => { },
    },
};

// 認証認可情報を管理するカスタムフック ///////////////////////////////////////////
export const useAuthNZ = (): UseAuthNZReturn => {
    // 認証情報の状態管理
    // const [is_auth_n, setIsAuthN] = useState<boolean | undefined>(default_auth_n_info.is_auth_n);
    const [is_auth_n, setIsAuthN] = useState<boolean | undefined>(default_auth_n_info.is_auth_n);
    // ユーザー情報
    const [user_info, setUserInfo] = useState<AuthUserInfo | undefined>(default_auth_n_info.user_info);
    // 認可情報の状態管理
    const [is_auth_z, setIsAuthZ] = useState<boolean | undefined>(default_auth_z_info.is_auth_z);
    // ロール情報の状態管理
    const [roles, setRoles] = useSessionStorage<string | undefined>(STORAGE_KEY.ROLES, default_auth_z_info.roles);
    // パーミッション情報の状態管理
    const [permissions, setPermissions] = useSessionStorage<string[] | undefined>(STORAGE_KEY.PERMISSIONS, default_auth_z_info.permissions);

    // ログイン処理の関数
    const login = (response: AuthStatusResponse) => {
        setIsAuthN(response.authenticated);
        setUserInfo(toUserInfo(response));
        setIsAuthZ(true); // 暫定的に認可も成功とする。実際にはここでロールやパーミッションの情報もセットする必要がある。
    };
    // ログアウト処理の関数
    const logout = () => {
        setIsAuthN(false);
        setUserInfo(undefined);
        setRoles(undefined);
        setPermissions(undefined);
    };

    // ステータス確認のリソースオブジェクトを定義 (アプリケーションプレーンのセッション)
    const auth_status_resource: ResourceObj<AuthStatusResponse> = {
        url: AUTH_API.APP_STATUS,
        method: 'GET',
        credentials: 'include',
    };


    useEffect(() => {
        requestFetch(auth_status_resource).then((data: AuthStatusResponse | null) => {
            if (!data) throw new Error('認証ステータスの取得に失敗');
            setIsAuthN(Boolean(data.authenticated));
            setUserInfo(toUserInfo(data));
        }).catch(() => {
            // 未認証は 401 (Problem Details の code: unauthenticated / session_expired) で返る。
            // 503 などそれ以外のエラーも、現状は未認証として扱いログイン画面へ誘導する。
            setIsAuthN(false);
            setUserInfo(undefined);
        });
    }, []);

    // 認証情報と認可情報をまとめて返す
    const auth_n_info = { is_auth_n, setIsAuthN } as AuthNInfo;
    const auth_z_info = { is_auth_z, setIsAuthZ, roles, setRoles, permissions, setPermissions } as AuthZInfo;
    const auth_status = { is_auth_n, is_auth_z } as Status;
    const command = { login, logout };

    return { auth_n_info, auth_z_info, auth_status, user_info, command };
};

export default useAuthNZ;