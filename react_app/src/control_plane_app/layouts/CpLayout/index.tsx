/**
 * @desc CP の認証後のレイアウト (RequireCpSession の内側で使う)
 * ヘッダーに「コントロールプレーン」・ユーザー名・ログアウト、その下にナビゲーションを出す。表示の骨格は shared の AppShell に任せ、
 * この層はセッション・権限とログアウトの接続、CP の配色 (cp_theme)、項目の定義だけを持つ。
 * saas_viewer には変更操作の UI を出さない (01 §11.2)。
 */
import { Outlet } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { useCpAuth, useCpPermissions, useCpSession } from '@/control_plane_app/auth/useCpAuth';
import { CP_HOME_PATH } from '@/control_plane_app/paths';
import { AppShell } from '@/shared/layouts/AppShell';
import { cp_theme } from '@/theme';
import { cpNavItemsOf, cpPermissionLabelOf } from './labels';

export const CpLayout = () => {
    const { user } = useCpSession();
    const permissions = useCpPermissions();
    const { logout } = useCpAuth();
    return (
        <ThemeProvider theme={cp_theme}>
            <AppShell
                title="コントロールプレーン"
                caption="SaaS 管理"
                title_to={CP_HOME_PATH}
                badge_label="管理画面"
                icon={<AdminPanelSettingsIcon />}
                user_name={user.preferred_username ?? user.email ?? user.sub}
                user_note={cpPermissionLabelOf(permissions)}
                nav_items={cpNavItemsOf(permissions)}
                nav_label="管理メニュー"
                onLogout={logout}
            >
                <Outlet />
            </AppShell>
        </ThemeProvider>
    );
};

export default CpLayout;
