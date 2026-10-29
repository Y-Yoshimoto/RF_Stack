// 認証関連ページ (ランディング・ログイン・テナントのエラー) のベースレイアウトコンポーネント
// プレーン固有のロジックは含めない。AP / CP のログイン画面で共通に使う。
import { use, type ReactNode } from 'react';
import { Outlet } from 'react-router-dom';

// MUIのコンポーネント
import { Container } from '@mui/material';
import { AuthContainerContext } from './auth_container_context';

/**
 * 認証関連ページの外枠 (中央寄せの幅の狭いコンテナ)
 * AuthLayout の内側など、既に外枠の中にある場合は何も足さずに子をそのまま返す (余白が二重にならない)。
 * ランディングのように AuthLayout の外に置かれるページは、この外枠で自分を包む。
 */
export const AuthContainer = ({ children }: { children: ReactNode }) => {
    const inside = use(AuthContainerContext);
    if (inside) return children;
    return (
        <AuthContainerContext value={true}>
            <Container maxWidth="sm" sx={{ py: { xs: 4, sm: 8 } }}>{children}</Container>
        </AuthContainerContext>
    );
};

export const AuthLayout = () => {
    return (
        <AuthContainer>
            <Outlet />
        </AuthContainer>
    );
};

export default AuthLayout;
