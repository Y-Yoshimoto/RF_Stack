/**
 * @desc AP の認証後画面のルートガード
 * 「AP セッションが認証済み」かつ「セッションのテナントコード = URL のテナントコード」のときだけ子ルートを表示する (01 §11.2)。
 * - 未認証: `/{tenantCode}/login` へリダイレクト
 * - 別テナントでログイン中: エラー画面 (mismatch)
 * - API の 403 でテナントの停止・利用不可が分かった: エラー画面 (suspended / unavailable)
 * - 状態の取得失敗 (401 以外): 例外を送出し、ルートのエラーバウンダリーに任せる
 */
import { Navigate, Outlet } from 'react-router-dom';
import { appLoginPath } from '@/main_app/paths';
import { TenantErrorPage } from '@/main_app/pages/TenantError';
import { PageLoading } from '@/shared/components/PageLoading';
import { decideAppAccess } from './guard';
import { useAppAuth, useUrlTenantCode } from './useAppAuth';

export const RequireAppSession = () => {
    const tenant_code = useUrlTenantCode();
    const { state, blocked, logout } = useAppAuth();
    const decision = decideAppAccess(state, tenant_code, blocked);
    switch (decision.type) {
        case 'loading':
            return <PageLoading />;
        case 'redirect_login':
            return <Navigate to={appLoginPath(tenant_code)} replace />;
        case 'tenant_mismatch':
            return <TenantErrorPage kind="mismatch" tenant_code={tenant_code} session_tenant_code={decision.session_tenant_code} onLogout={logout} />;
        case 'tenant_blocked':
            return <TenantErrorPage kind={decision.reason} tenant_code={tenant_code} />;
        case 'error':
            throw decision.error;
        default:
            return <Outlet />;
    }
};

export default RequireAppSession;
