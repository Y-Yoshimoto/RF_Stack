/**
 * @desc AP の認証後のレイアウト (RequireAppSession の内側で使う)
 * ヘッダーにテナントコード・ユーザー名・ログアウト、その下にナビゲーションを出す。表示の骨格は shared の AppShell に任せ、
 * この層はセッションとログアウトの接続と、AP の項目の定義だけを持つ。
 */
import { Outlet } from 'react-router-dom';
import BusinessIcon from '@mui/icons-material/Business';
import { useAppAuth, useAppSession } from '@/main_app/auth/useAppAuth';
import { appHomePath } from '@/main_app/paths';
import { AppShell } from '@/shared/layouts/AppShell';
import { appNavItemsOf, appPrimaryRoleLabelOf } from './labels';

export const AppLayout = () => {
    const { tenant_code, user } = useAppSession();
    const { logout } = useAppAuth();
    return (
        <AppShell
            title={tenant_code}
            caption="テナント"
            title_to={appHomePath(tenant_code)}
            icon={<BusinessIcon />}
            user_name={user.preferred_username ?? user.email ?? user.sub}
            user_note={appPrimaryRoleLabelOf(user.roles)}
            nav_items={appNavItemsOf(tenant_code)}
            onLogout={logout}
        >
            <Outlet />
        </AppShell>
    );
};

export default AppLayout;
