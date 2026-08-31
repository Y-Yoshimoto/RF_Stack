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
    const { userInfo } = use(AuthNZContext);

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
            </Typography>
            <LoginForm />
            {userInfo?.preferred_username && (
                <Typography variant="body2" align="center" sx={{ mt: 2 }}>
                    現在のユーザー: {userInfo.preferred_username}
                </Typography>
            )}
        </>
    );
};

// ログインフォームコンポーネント
const LoginForm: React.FC = () => {
    const [realm, setRealm] = useState('');
    const [isError, setIsError] = useState(false);

    const submit = () => {
        const realmName = realm.trim();
        if (!realmName) {
            setIsError(true);
            return;
        }
        const url = `/api/auth/login?realm=${encodeURIComponent(realmName)}`;
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
                    if (isError) setIsError(false);
                }}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') submit();
                }}
            />
            <Button variant="contained" color="primary" fullWidth onClick={submit}>
                ログイン
            </Button>
            {isError && <Typography color="error">テナント名を入力してください</Typography>}
        </Box>
    );
};

export default LoginPage;