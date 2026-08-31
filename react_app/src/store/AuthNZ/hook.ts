// 認証, 認可情報を管理するカスタムフック
import { useEffect, useState } from 'react';
import { useSessionStorage } from 'react-use';
// 定数のインポート
import { STORAGE_KEY } from '@/constants.ts';

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
// デフォルト値の設定 ////////////////////////////////////////////////////////////
const defaultAuthNInfo: AuthNInfo = {
    isAuthN: undefined,
    setIsAuthN: () => { },
    userInfo: undefined,
    setUserInfo: () => { },
};
const defaultAuthZInfo: AuthZInfo = {
    isAuthZ: undefined,
    setIsAuthZ: () => { },
    roles: undefined,
    setRoles: () => { },
    permissions: undefined,
    setPermissions: () => { },
};
const defaultStatus: Status = {
    isAuthN: undefined,
    isAuthZ: undefined,
};
export const defaultReturnValue: UseAuthNZReturn = {
    authNInfo: defaultAuthNInfo,
    authZInfo: defaultAuthZInfo,
    userInfo: defaultAuthNInfo.userInfo,
    authStatus: defaultStatus,
    command: {
        login: () => { },
        logout: () => { },
    },
};

// 認証認可情報を管理するカスタムフック ///////////////////////////////////////////
export const useAuthNZ = (): UseAuthNZReturn => {
    // 認証情報の状態管理
    // const [isAuthN, setIsAuthN] = useState<boolean | undefined>(defaultAuthNInfo.isAuthN);
    const [isAuthN, setIsAuthN] = useState<boolean | undefined>(defaultAuthNInfo.isAuthN);
    // ユーザー情報
    const [userInfo, setUserInfo] = useState<AuthUserInfo | undefined>(defaultAuthNInfo.userInfo);
    // 認可情報の状態管理
    const [isAuthZ, setIsAuthZ] = useState<boolean | undefined>(defaultAuthZInfo.isAuthZ);
    // ロール情報の状態管理
    const [roles, setRoles] = useSessionStorage<string | undefined>(STORAGE_KEY.ROLES, defaultAuthZInfo.roles);
    // パーミッション情報の状態管理
    const [permissions, setPermissions] = useSessionStorage<string[] | undefined>(STORAGE_KEY.PERMISSIONS, defaultAuthZInfo.permissions);

    // ログイン処理の関数
    const login = (response: AuthStatusResponse) => {
        setIsAuthN(response.authenticated);
        setUserInfo(response.user);
        setIsAuthZ(true); // 暫定的に認可も成功とする。実際にはここでロールやパーミッションの情報もセットする必要がある。
    };
    // ログアウト処理の関数
    const logout = () => {
        setIsAuthN(false);
        setUserInfo(undefined);
        setRoles(undefined);
        setPermissions(undefined);
    };

    // ステータス確認のリソースオブジェクトを定義
    const authStatusResource: ResourceObj<AuthStatusResponse> = {
        url: '/api/auth/status',
        method: 'GET',
        credentials: 'include',
    };


    useEffect(() => {
        requestFetch(authStatusResource).then((data: AuthStatusResponse | null) => {
            if (!data) throw new Error('認証ステータスの取得に失敗');
            setIsAuthN(Boolean(data.authenticated));
            setUserInfo(data.user);
        }).catch(() => {
            setIsAuthN(false);
            setUserInfo(undefined);
        });
    }, []);

    // 認証情報と認可情報をまとめて返す
    const authNInfo = { isAuthN, setIsAuthN } as AuthNInfo;
    const authZInfo = { isAuthZ, setIsAuthZ, roles, setRoles, permissions, setPermissions } as AuthZInfo;
    const authStatus = { isAuthN, isAuthZ } as Status;
    const command = { login, logout };

    return { authNInfo, authZInfo, authStatus, userInfo, command };
};

export default useAuthNZ;