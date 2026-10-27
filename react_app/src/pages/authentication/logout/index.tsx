// ログアウトボタンを表示する検証用ページ
import React from 'react';
// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';
import { useNavigate } from 'react-router-dom';
// MUIのコンポーネント
import { Typography, Button } from '@mui/material';

const LogoutPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { auth_n_info, command } = use(AuthNZContext);
    const navigate = useNavigate();

    const logout = async () => {
        // FastAPI 側はリダイレクトではなく KeyCloak のログアウト URL を JSON で返す。
        // KeyCloak の SSO セッション終了はフロントチャネル (RP-Initiated Logout) で行うため、
        // fetch ではなく window.location によるトップレベル遷移が必要になる。
        const logout_url = await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include',
        })
            .then(res => (res.ok ? res.json() : null))
            .then(body => body?.logout_url ?? null)
            .catch(() => null);

        // ローカルの認証状態は遷移前に必ずクリアする
        command.logout();

        if (logout_url) {
            window.location.href = logout_url;
            return;
        }
        // ログアウト URL を取得できなかった場合はローカル遷移のみ行う
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

const LogoutForm: React.FC = ({ logout }: any) => {

    return (
        <Button variant="contained" color="primary" fullWidth onClick={() => logout()}>
            ログアウト
        </Button>
    )
};

export default LogoutPage;