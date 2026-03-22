// 認証認可コンテキストプロバーダー
import { createContext, ReactNode } from 'react';
import useAuthNZ from './hook';

// 認証認可コンテキストの作成
export const AuthNZContext = createContext<ReturnType<typeof useAuthNZ> | null>(null);

// 認証認可プロバイダーコンポーネント
export const AuthNZProvider = ({ children }: { children: ReactNode }) => {
    const { authNInfo, authZInfo, authStatus } = useAuthNZ();

    return (
        <AuthNZContext.Provider value={{ authNInfo, authZInfo, authStatus }}>
            {children}
        </AuthNZContext.Provider>
    );
}