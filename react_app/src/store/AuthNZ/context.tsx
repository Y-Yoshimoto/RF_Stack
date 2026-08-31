// 認証認可コンテキストプロバーダー
import { createContext, ReactNode } from 'react';
import { useAuthNZ, defaultReturnValue } from './hook';
import type { UseAuthNZReturn } from './type';

// 認証認可コンテキストの作成
export const AuthNZContext = createContext<UseAuthNZReturn>(defaultReturnValue);

// 認証認可プロバイダーコンポーネント
export const AuthNZProvider = ({ children }: { children: ReactNode }) => {
    const authNZ = useAuthNZ();

    return (
        <AuthNZContext value={authNZ}>
            {children}
        </AuthNZContext>
    );
}