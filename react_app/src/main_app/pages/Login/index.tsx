/**
 * @desc AP のログイン画面 (`/{tenant_code}/login`)
 * テナントが利用可能なことを確認した後に表示される (AppLoginRoute)。
 * ログインは BFF のログイン開始 API へのトップレベル遷移で、パスワード入力はこの画面にない (認証基盤の画面で行う)。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Button, Chip, Link, Stack, Typography } from '@mui/material';
import LoginIcon from '@mui/icons-material/Login';
import BusinessIcon from '@mui/icons-material/Business';
import { LANDING_PATH } from '@/main_app/paths';
import { AuthCard } from '@/shared/components/AuthCard';
import { LoginErrorAlert } from '@/shared/components/LoginErrorAlert';

export type AppLoginPageProps = {
    /** テナントコード (URL)。 */
    tenant_code: string;
    /** クエリ `?error=` のエラーコード (shared/auth/type.ts の LOGIN_ERROR_CODE。無ければ null)。文言は loginErrorMessageOf で得る。 */
    error_code: string | null;
    /** ログインを開始する (BFF のログイン開始 API へトップレベル遷移する)。 */
    onLogin: () => void;
};

export const AppLoginPage = ({ tenant_code, error_code, onLogin }: AppLoginPageProps) => {
    return (
        <AuthCard
            test_id="app-login-page"
            title="ログイン"
            icon={<BusinessIcon />}
            description={
                <Stack spacing={1} sx={{ alignItems: 'center' }}>
                    <Typography variant="body2" color="text.secondary" component="span">次のテナントにログインします</Typography>
                    <Chip label={tenant_code} color="primary" variant="outlined" data-testid="app-login-tenant-code" />
                </Stack>
            }
        >
            <LoginErrorAlert error_code={error_code} />
            <Button type="button" variant="contained" size="large" fullWidth startIcon={<LoginIcon />} onClick={onLogin} data-testid="login-submit">
                ログイン
            </Button>
            <Typography variant="body2" component="p" sx={{ textAlign: 'center' }}>
                <Link component={RouterLink} to={LANDING_PATH} data-testid="login-change-tenant">別のテナントでログインする</Link>
            </Typography>
        </AuthCard>
    );
};

export default AppLoginPage;
