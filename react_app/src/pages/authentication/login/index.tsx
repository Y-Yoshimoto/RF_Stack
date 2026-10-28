// ログイン画面 (アプリケーションプレーン)
import React from 'react';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

// MUIのコンポーネント
import { Typography } from '@mui/material';
import { Box, Button, TextField } from '@mui/material';

// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';
// 認証 API のエンドポイント
import { AUTH_API } from '@/constants.ts';

// BFF がログインを開始できなかった場合のエラーコードと表示文言。
// テナントが存在しない・利用できないことは区別されない (テナントの存在を明かさないため)。
const LOGIN_ERROR_MESSAGES: Record<string, string> = {
    tenant_unavailable: 'このテナントは利用できません。テナントコードを確認してください',
};

const LoginPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { user_info } = use(AuthNZContext);

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
            </Typography>
            <LoginForm />
            {user_info?.preferred_username && (
                <Typography variant="body2" align="center" sx={{ mt: 2 }}>
                    現在のユーザー: {user_info.preferred_username}
                </Typography>
            )}
        </>
    );
};

// ログインフォームコンポーネント
// テナントコードを BFF のログイン開始 API (/api/auth/app/login?tenant_code=) に渡す。
// レルム名はフロントで扱わない (BFF がテナントレジストリで解決する)。
const LoginForm: React.FC = () => {
    const [search_params] = useSearchParams();
    const [tenant_code, setTenantCode] = useState('');
    const [is_error, setIsError] = useState(false);
    const login_error = LOGIN_ERROR_MESSAGES[search_params.get('error') ?? ''];

    const submit = () => {
        const code = tenant_code.trim().toLowerCase();
        if (!code) {
            setIsError(true);
            return;
        }
        // Cookie の付与と KeyCloak へのリダイレクト追従のため、fetch ではなくトップレベル遷移にする
        window.location.assign(`${AUTH_API.APP_LOGIN}?${new URLSearchParams({ tenant_code: code }).toString()}`);
    };

    return (
        <Box component="form" noValidate onSubmit={(e) => { e.preventDefault(); submit(); }}>
            <TextField
                label="テナントコード"
                variant="outlined"
                fullWidth
                margin="normal"
                name="tenant_code"
                autoComplete="organization"
                value={tenant_code}
                onChange={(e) => {
                    setTenantCode(e.target.value);
                    if (is_error) setIsError(false);
                }}
                slotProps={{ htmlInput: { 'data-testid': 'login-tenant-code' } }}
            />
            <Button type="submit" variant="contained" color="primary" fullWidth data-testid="login-submit">
                ログイン
            </Button>
            {is_error && <Typography color="error">テナントコードを入力してください</Typography>}
            {!is_error && login_error && <Typography color="error" data-testid="login-error">{login_error}</Typography>}
        </Box>
    );
};

export default LoginPage;
