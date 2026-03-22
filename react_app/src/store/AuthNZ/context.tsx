// 認証認可コンテキストプロバーダー
import { createContext, ReactNode } from 'react';
import { useAuthNZ, defaultReturnValue } from './hook';

// 認証認可コンテキストの作成
export const AuthNZContext = createContext<ReturnType<typeof useAuthNZ>>(defaultReturnValue);

// 認証認可プロバイダーコンポーネント
export const AuthNZProvider = ({ children }: { children: ReactNode }) => {
    const { authNInfo, authZInfo, authStatus } = useAuthNZ();

    return (
        <AuthNZContext value={{ authNInfo, authZInfo, authStatus }}>
            {children}
        </AuthNZContext>
    );
}