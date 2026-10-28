/**
 * @desc CP のログイン画面 (`/cp/login`)
 * テナントのログイン (AP) とは別の入口であることが分かるよう、CP のテーマ (cp_theme) で描画し、「管理者専用」を明示する。
 */
import { Button, Chip, GlobalStyles } from '@mui/material';
import { ThemeProvider } from '@mui/material/styles';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import LoginIcon from '@mui/icons-material/Login';
import { AuthCard } from '@/shared/components/AuthCard';
import { LoginErrorAlert } from '@/shared/components/LoginErrorAlert';
import { cp_theme } from '@/theme';

export type CpLoginPageProps = {
    /** クエリ `?error=` のエラーコード (shared/auth/type.ts の LOGIN_ERROR_CODE。無ければ null)。文言は loginErrorMessageOf で得る。 */
    error_code: string | null;
    /** ログインを開始する (BFF のログイン開始 API へトップレベル遷移する)。 */
    onLogin: () => void;
};

export const CpLoginPage = ({ error_code, onLogin }: CpLoginPageProps) => {
    return (
        <ThemeProvider theme={cp_theme}>
            {/* CP のログイン画面が表示されている間だけ、ページの背景を CP の色にする */}
            <GlobalStyles styles={(theme) => ({ body: { backgroundColor: theme.palette.background.default } })} />
            <AuthCard
                test_id="cp-login-page"
                title="コントロールプレーン"
                icon={<AdminPanelSettingsIcon />}
                description="SaaS 運用者向けの管理画面です。テナントの利用者の方は、テナントのログイン画面からログインしてください。"
            >
                <Chip label="管理者専用" color="secondary" size="small" sx={{ alignSelf: 'center' }} data-testid="cp-login-badge" />
                <LoginErrorAlert error_code={error_code} />
                <Button type="button" variant="contained" size="large" fullWidth startIcon={<LoginIcon />} onClick={onLogin} data-testid="login-submit">
                    ログイン
                </Button>
            </AuthCard>
        </ThemeProvider>
    );
};

export default CpLoginPage;
