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
    const { auth_n_info } = use(AuthNZContext);

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
                <LoginForm auth_n_info={auth_n_info} />
            </Typography>
        </>
    );
};

const LoginForm: React.FC<{ auth_n_info: AuthNInfo }> = ({ auth_n_info }) => {
    // フォームの状態管理
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');


    // リソースオブジェクト
    const [resource_obj, setResourceObj] = useState<any>(null);
    const resource_key = resource_obj ? generateRequestKey(resource_obj) : '';

    // リソース設定関数
    const Submit = () => {
        setResourceObj({
            url: '/api/login',
            method: 'POST',
            body: { username, password },
        });
    };

    const form_data = { username, setUsername, password, setPassword, Submit };

    // ログイン成功時の処理
    const successLogin = (response) => {
        // 認証情報を更新
        console.log('Login successful:', response);
        auth_n_info.setIsAuthN(true);
        // navigate('/'); // ログイン成功後の遷移先
    };

    return (
        <>
            {resource_obj
                ? <LoginFormRequest key={resource_key} resource_obj={resource_obj} form_data={form_data} successLogin={successLogin} />
                : <LoginFormBody form_data={form_data} loading={false} is_error={false} />}
        </>
    );
};

const LoginFormRequest: React.FC<{ resource_obj: ResourceObj; form_data: any; successLogin: (response: any) => void }> = ({ resource_obj, form_data, successLogin }) => {
    const { response, loading, error } = useFetch(resource_obj);

    // ログイン成功時の処理, 一度だけ実行するためにuseEffectを使用
    useEffect(() => {
        if (response) successLogin(response);
    }, [response]);

    // エラーステータス
    // ユーザー名とパスワードが変化しているかを確認する。
    const is_credential_changed = (resource_obj.body.username !== form_data.username) || (resource_obj.body.password !== form_data.password);
    // エラーが存在し、かつユーザー名またはパスワードが変化していない場合にエラーとする。
    const is_error = error ? !is_credential_changed : false;

    return (
        <LoginFormBody form_data={form_data} loading={loading} is_error={is_error} />
    );
};


// ログインフォームコンポーネント
const LoginFormBody: React.FC<{ form_data: any; loading: boolean; is_error: boolean }> = ({ form_data, loading, is_error }) => {
    const { username, setUsername, password, setPassword, Submit } = form_data;
    return (
        <Box component="form" noValidate autoComplete="off">
            <TextField label="ユーザー名" variant="outlined" fullWidth margin="normal" value={username} onChange={(e) => setUsername(e.target.value)} />
            <TextField label="パスワード" type="password" variant="outlined" fullWidth margin="normal" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button variant="contained" color="primary" fullWidth onClick={() => Submit()} disabled={loading || is_error}>
                ログイン
            </Button>
            {is_error && <Typography color="error">ユーザー名またはパスワードが正しくありません</Typography>}
        </Box>
    );
};

export default LoginPage;