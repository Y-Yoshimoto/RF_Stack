// 認証認可関連ページのベースレイアウトコンポーネント
import { Outlet } from 'react-router-dom';

// MUIのコンポーネント
import { Container, Typography } from '@mui/material';

const AuthLayout = () => {
    return (
        <Container maxWidth="sm" sx={{ mt: 8 }}>
            <Outlet />
        </Container>
    );
};

export default AuthLayout;