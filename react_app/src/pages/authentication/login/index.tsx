// ログイン画面
import React from 'react';
import { useState } from 'react';

// MUIのコンポーネント
import { Typography } from '@mui/material';
import { Box, Button, TextField } from '@mui/material';

// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';

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
const LoginForm: React.FC = () => {
    const [realm, setRealm] = useState('');
    const [is_error, setIsError] = useState(false);

    const submit = () => {
        const realm_name = realm.trim();
        if (!realm_name) {
            setIsError(true);
            return;
        }
        const url = `/api/auth/login?realm=${encodeURIComponent(realm_name)}`;
        window.location.assign(url);
    };

    return (
        <Box component="form" noValidate>
            <TextField
                label="テナント名 (Realm)"
                variant="outlined"
                fullWidth
                margin="normal"
                name="realm"
                autoComplete="on"
                value={realm}
                onChange={(e) => {
                    setRealm(e.target.value);
                    if (is_error) setIsError(false);
                }}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') submit();
                }}
            />
            <Button variant="contained" color="primary" fullWidth onClick={submit}>
                ログイン
            </Button>
            {is_error && <Typography color="error">テナント名を入力してください</Typography>}
        </Box>
    );
};

export default LoginPage;