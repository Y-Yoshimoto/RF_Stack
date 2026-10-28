/**
 * @desc ログイン画面・ランディングの `?error=<code>` を表示するアラート
 * 文言は loginErrorMessageOf が決める。MUI の Alert は role="alert" を持つため、表示された時点でスクリーンリーダーが読み上げる。
 */
import { Alert } from '@mui/material';
import { loginErrorMessageOf } from '@/shared/auth/login_error';

export type LoginErrorAlertProps = {
    /** エラーコード (`?error=` の値。無ければ何も表示しない)。 */
    error_code: string | null;
};

export const LoginErrorAlert = ({ error_code }: LoginErrorAlertProps) => {
    const message = loginErrorMessageOf(error_code);
    if (!message) return null;
    return (
        <Alert severity="error" data-testid="login-error" data-code={error_code}>
            {message}
        </Alert>
    );
};

export default LoginErrorAlert;
