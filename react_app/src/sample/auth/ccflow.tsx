// サーバーを中継して "Client credentials flow"でアクセストークンを取得するサンプルコード
// ログイン画面
// 注意: 呼び出し先の /api/login は FastAPI に存在しない (参考用のサンプル。どのルートにも登録していない)。
// 旧 store/AuthNZ の setIsAuthN(true) の代わりに、ログイン成功時は AP の認証状態を再取得する (AppAuthProvider の内側で使う)。
import React from 'react';
import { useState, useEffect } from 'react';

// MUIのコンポーネント
import { Typography } from '@mui/material';
// MUIのコンポーネント
import { Box, Button, TextField } from '@mui/material';

// 認証コンテキスト (アプリケーションプレーン)
import { useAppAuth } from '@/main_app/auth/useAppAuth';

// Fetchフック
import { useFetch, generateRequestKey, type ResourceObj } from '@/utils/libs/FetchComponents';

// ログイン API のレスポンス (サンプルのため形は規定しない)
type LoginResponse = Record<string, unknown>;

// ログインの認証情報
type LoginCredentials = {
    username: string;
    password: string;
};

// フォームの状態と操作
type LoginFormData = LoginCredentials & {
    setUsername: (value: string) => void;
    setPassword: (value: string) => void;
    submit: () => void;
};

const LoginPage: React.FC = () => {
    // 認証状態 (ログイン成功時に再取得する)
    const { refresh } = useAppAuth();

    return (
        <>
            <Typography variant="h4" align="center" gutterBottom>
                ログインページ
                <LoginForm onLoginSuccess={refresh} />
            </Typography>
        </>
    );
};

const LoginForm: React.FC<{ onLoginSuccess: () => void }> = ({ onLoginSuccess }) => {
    // フォームの状態管理
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');


    // 送信した認証情報 (リソースオブジェクトの元)
    const [submitted, setSubmitted] = useState<LoginCredentials | null>(null);
    const resource_obj: ResourceObj<LoginResponse> | null = submitted ? { url: '/api/login', method: 'POST', body: submitted } : null;
    const resource_key = resource_obj ? generateRequestKey(resource_obj) : '';

    // リソース設定関数
    const submit = () => {
        setSubmitted({ username, password });
    };

    const form_data: LoginFormData = { username, setUsername, password, setPassword, submit };

    // ログイン成功時の処理
    const successLogin = (response: LoginResponse) => {
        // 認証情報を更新
        console.log('Login successful:', response);
        onLoginSuccess();
        // navigate('/'); // ログイン成功後の遷移先
    };

    return (
        <>
            {resource_obj && submitted
                ? <LoginFormRequest key={resource_key} resource_obj={resource_obj} submitted={submitted} form_data={form_data} successLogin={successLogin} />
                : <LoginFormBody form_data={form_data} loading={false} is_error={false} />}
        </>
    );
};

type LoginFormRequestProps = {
    resource_obj: ResourceObj<LoginResponse>;
    submitted: LoginCredentials;
    form_data: LoginFormData;
    successLogin: (response: LoginResponse) => void;
};

const LoginFormRequest: React.FC<LoginFormRequestProps> = ({ resource_obj, submitted, form_data, successLogin }) => {
    const { response, loading, error } = useFetch(resource_obj);

    // ログイン成功時の処理, 一度だけ実行するためにuseEffectを使用
    useEffect(() => {
        if (response) successLogin(response);
    }, [response]);

    // エラーステータス
    // ユーザー名とパスワードが変化しているかを確認する。
    const is_credential_changed = (submitted.username !== form_data.username) || (submitted.password !== form_data.password);
    // エラーが存在し、かつユーザー名またはパスワードが変化していない場合にエラーとする。
    const is_error = error ? !is_credential_changed : false;

    return (
        <LoginFormBody form_data={form_data} loading={loading} is_error={is_error} />
    );
};


// ログインフォームコンポーネント
const LoginFormBody: React.FC<{ form_data: LoginFormData; loading: boolean; is_error: boolean }> = ({ form_data, loading, is_error }) => {
    const { username, setUsername, password, setPassword, submit } = form_data;
    return (
        <Box component="form" noValidate autoComplete="off">
            <TextField label="ユーザー名" variant="outlined" fullWidth margin="normal" value={username} onChange={(e) => setUsername(e.target.value)} />
            <TextField label="パスワード" type="password" variant="outlined" fullWidth margin="normal" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button variant="contained" color="primary" fullWidth onClick={() => submit()} disabled={loading || is_error}>
                ログイン
            </Button>
            {is_error && <Typography color="error">ユーザー名またはパスワードが正しくありません</Typography>}
        </Box>
    );
};

export default LoginPage;
