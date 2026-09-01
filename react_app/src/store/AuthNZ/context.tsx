// 認証認可コンテキストプロバーダー
import { createContext, ReactNode } from 'react';
import { useAuthNZ, default_return_value } from './hook';
import type { UseAuthNZReturn } from './type';

// 認証認可コンテキストの作成
export const AuthNZContext = createContext<UseAuthNZReturn>(default_return_value);

// 認証認可プロバイダーコンポーネント
export const AuthNZProvider = ({ children }: { children: ReactNode }) => {
    const auth_nz = useAuthNZ();

    return (
        <AuthNZContext value={auth_nz}>
            {children}
        </AuthNZContext>
    );
}