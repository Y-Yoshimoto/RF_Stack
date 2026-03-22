// ログイン画面
import React from 'react';
import { useState, useEffect } from 'react';
// ナビゲーション用のフック
import { useNavigate } from 'react-router-dom';

// MUIのコンポーネント
import { Container, Typography } from '@mui/material';
// MUIのコンポーネント
import { Box, Button, TextField } from '@mui/material';

// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';

// Fetchフック
import useFetch from '@/utils/libs/FetchComponents/hook';
import { generateRequestKey } from '@/utils/libs/FetchComponents/common';

const LoginPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { authNInfo } = use(AuthNZContext);

    // ルーターからナビゲーション関数を取得
    const navigate = useNavigate();

    console.log('LoginPage authNInfo:', authNInfo);

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
                <LoginForm authNInfo={authNInfo} navigate={navigate} />
            </Typography>
        </>
    );
};

const LoginForm: React.FC = ({ authNInfo, navigate }: any) => {
    // フォームの状態管理
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');


    // リソースオブジェクト
    const [resourceObj, setResourceObj] = useState(null);
    const resourceKey = resourceObj ? generateRequestKey(resourceObj) : '';

    // リソース設定関数
    const Submit = () => {
        setResourceObj({
            url: '/api/login',
            method: 'POST',
            body: { username, password },
        });
    };

    const formData = { username, setUsername, password, setPassword, Submit };

    // ログイン成功時の処理
    const SuccessLogin = (response) => {
        // 認証情報を更新
        console.log('Login successful:', response);
        authNInfo.setIsAuthN(true);
        // navigate('/'); // ログイン成功後の遷移先
    };

    return (
        <>
            {resourceObj
                ? <LoginFormRequest key={resourceKey} resourceObj={resourceObj} formData={formData} SuccessLogin={SuccessLogin} />
                : <LoginFormBody formData={formData} loading={false} error={null} />}
        </>
    );
};

const LoginFormRequest: React.FC = ({ resourceObj, formData, SuccessLogin }: any) => {
    const { response, loading, error } = useFetch(resourceObj);

    // ログイン成功時の処理, 一度だけ実行するためにuseEffectを使用
    useEffect(() => {
        response && SuccessLogin(response);
    }, [response]);

    return (
        <LoginFormBody formData={formData} loading={loading} error={error} />
    );
};


// ログインフォームコンポーネント
const LoginFormBody: React.FC = ({ formData, loading, error }: any) => {
    const { username, setUsername, password, setPassword, Submit } = formData;
    console.log('LoginFormBody:', { username, password, loading, error });

    return (
        <Box component="form" noValidate autoComplete="off">
            <TextField label="ユーザー名" variant="outlined" fullWidth margin="normal" value={username} onChange={(e) => setUsername(e.target.value)} />
            <TextField label="パスワード" type="password" variant="outlined" fullWidth margin="normal" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button variant="contained" color="primary" fullWidth onClick={() => Submit()}>
                ログイン
            </Button>
            {loading && <Typography>Loading...</Typography>}
            {error && <Typography color="error">{error.message}</Typography>}
        </Box>
    );
};

export default LoginPage;