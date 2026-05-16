// ログアウトボタンを表示する検証用ページ
import React from 'react';
// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';
// MUIのコンポーネント
import { Typography, Button } from '@mui/material';
import { useNavigate } from 'react-router-dom';

const LogoutPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { authNInfo } = use(AuthNZContext);
    const navigate = useNavigate();

    const logout = async () => {
        await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include',
        });
        authNInfo.setIsAuthN(false);
        navigate('/login');
    };

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログアウトページ
                <LogoutForm logout={logout} />
            </Typography>
        </>
    );
};

const LogoutForm: React.FC<{ logout: () => Promise<void> }> = ({ logout }) => {

    return (
        <Button variant="contained" color="primary" fullWidth onClick={() => logout()}>
            ログアウト
        </Button>
    )
};

export default LogoutPage;
