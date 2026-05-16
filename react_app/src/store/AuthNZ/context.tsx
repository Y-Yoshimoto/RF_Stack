// 認証認可コンテキストプロバーダー
import { createContext, ReactNode, useEffect } from 'react';
import { useAuthNZ, defaultReturnValue } from './hook';

// 認証認可コンテキストの作成
export const AuthNZContext = createContext<ReturnType<typeof useAuthNZ>>(defaultReturnValue);

// 認証認可プロバイダーコンポーネント
export const AuthNZProvider = ({ children }: { children: ReactNode }) => {
    const { authNInfo, authZInfo, authStatus } = useAuthNZ();
    const { setIsAuthN } = authNInfo;
    const { setIsAuthZ, setPermissions } = authZInfo;

    useEffect(() => {
        fetch('/api/auth/session', { credentials: 'include' })
            .then((res) => {
                if (!res.ok) {
                    throw new Error('session check failed');
                }
                return res.json();
            })
            .then((session) => {
                setIsAuthN(!!session.isAuthN);
                setPermissions(Array.isArray(session.permissions) ? session.permissions : undefined);
                setIsAuthZ(Array.isArray(session.roles) ? session.roles.length > 0 : false);
            })
            .catch(() => {
                setIsAuthN(false);
                setIsAuthZ(false);
            });
    }, [setIsAuthN, setIsAuthZ, setPermissions]);

    return (
        <AuthNZContext value={{ authNInfo, authZInfo, authStatus }}>
            {children}
        </AuthNZContext>
    );
}
