// サーバーを中継して "Client credentials flow"でアクセストークンを取得するサンプルコード
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
import { AuthNZContext, AuthNInfo } from '@/store/AuthNZ';

// Fetchフック
import { useFetch, generateRequestKey, ResourceObj } from '@/utils/libs/FetchComponents';
const LoginPage: React.FC = () => {
    // 認証認可コンテキストから認証情報を取得
    const { authNInfo } = use(AuthNZContext);

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
                <LoginForm authNInfo={authNInfo} />
            </Typography>
        </>
    );
};

const LoginForm: React.FC<{ authNInfo: AuthNInfo }> = ({ authNInfo }) => {
    // フォームの状態管理
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');


    // リソースオブジェクト
    const [resourceObj, setResourceObj] = useState<any>(null);
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
                : <LoginFormBody formData={formData} loading={false} isError={false} />}
        </>
    );
};

const LoginFormRequest: React.FC<{ resourceObj: ResourceObj; formData: any; SuccessLogin: (response: any) => void }> = ({ resourceObj, formData, SuccessLogin }) => {
    const { response, loading, error } = useFetch(resourceObj);

    // ログイン成功時の処理, 一度だけ実行するためにuseEffectを使用
    useEffect(() => {
        if (response) SuccessLogin(response);
    }, [response]);

    // エラーステータス
    // ユーザー名とパスワードが変化しているかを確認する。
    const isCredentialChanged = (resourceObj.body.username !== formData.username) || (resourceObj.body.password !== formData.password);
    // エラーが存在し、かつユーザー名またはパスワードが変化していない場合にエラーとする。
    const isError = error ? !isCredentialChanged : false;

    return (
        <LoginFormBody formData={formData} loading={loading} isError={isError} />
    );
};


// ログインフォームコンポーネント
const LoginFormBody: React.FC<{ formData: any; loading: boolean; isError: boolean }> = ({ formData, loading, isError }) => {
    const { username, setUsername, password, setPassword, Submit } = formData;
    return (
        <Box component="form" noValidate autoComplete="off">
            <TextField label="ユーザー名" variant="outlined" fullWidth margin="normal" value={username} onChange={(e) => setUsername(e.target.value)} />
            <TextField label="パスワード" type="password" variant="outlined" fullWidth margin="normal" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button variant="contained" color="primary" fullWidth onClick={() => Submit()} disabled={loading || isError}>
                ログイン
            </Button>
            {isError && <Typography color="error">ユーザー名またはパスワードが正しくありません</Typography>}
        </Box>
    );
};

export default LoginPage;