// 認証, 認可情報を管理するカスタムフック
import { useState } from 'react';
import { useSessionStorage } from 'react-use';
// 定数のインポート
import { STORAGE_KEY } from '@/constants.ts';

// カスタムフックの型定義 //////////////////////////////////////////////////////////////////
export interface AuthNInfo {
    isAuthN: boolean | undefined;
    setIsAuthN: React.Dispatch<React.SetStateAction<boolean | undefined>>;
}
export interface AuthZInfo {
    isAuthZ: boolean | undefined;
    setIsAuthZ: React.Dispatch<React.SetStateAction<boolean | undefined>>;
    roles: string | undefined;
    setRoles: React.Dispatch<React.SetStateAction<string | undefined>>;
    permissions: string[] | undefined;
    setPermissions: React.Dispatch<React.SetStateAction<string[] | undefined>>;
}
export interface Status {
    isAuthN: boolean | undefined;
    isAuthZ: boolean | undefined;
}

export interface UseAuthNZReturn {
    authNInfo: AuthNInfo;
    authZInfo: AuthZInfo;
    authStatus: Status;
}
// デフォルト値の設定 ////////////////////////////////////////////////////////////
const defaultAuthNInfo: AuthNInfo = {
    isAuthN: false,
    setIsAuthN: () => { },
};
const defaultAuthZInfo: AuthZInfo = {
    isAuthZ: false,
    setIsAuthZ: () => { },
    roles: undefined,
    setRoles: () => { },
    permissions: undefined,
    setPermissions: () => { },
};
const defaultStatus: Status = {
    isAuthN: false,
    isAuthZ: false,
};
export const defaultReturnValue: UseAuthNZReturn = {
    authNInfo: defaultAuthNInfo,
    authZInfo: defaultAuthZInfo,
    authStatus: defaultStatus,
};

// 認証認可情報を管理するカスタムフック ///////////////////////////////////////////
export const useAuthNZ = (): UseAuthNZReturn => {
    // 認証情報の状態管理
    // const [isAuthN, setIsAuthN] = useState<boolean | undefined>(defaultAuthNInfo.isAuthN);
    const [isAuthN, setIsAuthN] = useState<boolean | undefined>(defaultAuthNInfo.isAuthN);
    // 認可情報の状態管理
    const [isAuthZ, setIsAuthZ] = useState<boolean | undefined>(defaultAuthZInfo.isAuthZ);
    // ロール情報の状態管理
    const [roles, setRoles] = useSessionStorage<string | undefined>(STORAGE_KEY.ROLES, defaultAuthZInfo.roles);
    // パーミッション情報の状態管理
    const [permissions, setPermissions] = useSessionStorage<string[] | undefined>(STORAGE_KEY.PERMISSIONS, defaultAuthZInfo.permissions);

    // 認証情報と認可情報をまとめて返す
    const authNInfo = { isAuthN, setIsAuthN } as AuthNInfo;
    const authZInfo = { isAuthZ, setIsAuthZ, roles, setRoles, permissions, setPermissions } as AuthZInfo;
    const authStatus = { isAuthN, isAuthZ } as Status;

    return { authNInfo, authZInfo, authStatus };
};

export default useAuthNZ;
