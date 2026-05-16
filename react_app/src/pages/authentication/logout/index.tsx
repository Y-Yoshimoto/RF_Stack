// ログアウトボタンを表示する検証用ページ
import React from 'react';
// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';
// MUIのコンポーネント
import { Typography, Button } from '@mui/material';

const LogoutPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { authNInfo } = use(AuthNZContext);

    const logout = () => {
        authNInfo.setIsAuthN(false);
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

const LogoutForm: React.FC = ({ logout }: any) => {

    return (
        <Button variant="contained" color="primary" fullWidth onClick={() => logout()}>
            ログアウト
        </Button>
    )
};

export default LogoutPage;