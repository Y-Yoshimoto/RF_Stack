// ログアウトボタンを表示する検証用ページ
import React from 'react';
// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';
import type { LogoutResponse } from '@/store/AuthNZ';
import { useNavigate } from 'react-router-dom';
// 認証 API のエンドポイント
import { AUTH_API } from '@/constants.ts';
// httpリクエスト (変更系メソッドには CSRF 対策ヘッダーが自動で付与される)
import { requestFetch } from '@/utils/libs/FetchComponents';
// MUIのコンポーネント
import { Typography, Button } from '@mui/material';

const LogoutPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { command } = use(AuthNZContext);
    const navigate = useNavigate();

    const logout = async () => {
        // FastAPI 側はリダイレクトではなく KeyCloak のログアウト URL を JSON で返す。
        // KeyCloak の SSO セッション終了はフロントチャネル (RP-Initiated Logout) で行うため、
        // fetch ではなく window.location によるトップレベル遷移が必要になる。
        // 変更系のため CSRF 対策ヘッダーが必須 (無いと 403 csrf_validation_failed)。
        // requestFetch が X-Requested-With: rf-stack を付与し、Origin はブラウザが付与する。
        const logout_url = await requestFetch<LogoutResponse>({ url: AUTH_API.APP_LOGOUT, method: 'POST' })
            .then((body) => body?.logout_url ?? null)
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

// ログアウトボタンコンポーネント
type LogoutFormProps = {
    /** ログアウト処理。 */
    logout: () => Promise<void>;
};

const LogoutForm: React.FC<LogoutFormProps> = ({ logout }) => {

    return (
        <Button variant="contained" color="primary" fullWidth onClick={() => logout()}>
            ログアウト
        </Button>
    )
};

export default LogoutPage;