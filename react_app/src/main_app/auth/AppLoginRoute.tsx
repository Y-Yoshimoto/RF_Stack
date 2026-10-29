/**
 * @desc AP のログイン画面 (`/:tenantCode/login`) のルート
 * 1. セッションを確認する (同じテナントで認証済みならホームへ、別テナントなら「別テナントでログイン中」)
 * 2. 未認証なら公開のテナント存在確認 API でテナントの利用可否を確認する
 * 3. 利用できればログイン画面、できなければエラー画面 (不在・停止中・利用不可)
 * 401 以外の失敗 (状態 API・存在確認 API の 429 / 503 等) は例外を送出し、ルートのエラーバウンダリーに任せる。
 */
import { Navigate } from 'react-router-dom';
import { AppLoginPage } from '@/main_app/pages/Login';
import { TenantErrorPage } from '@/main_app/pages/TenantError';
import { appHomePath } from '@/main_app/paths';
import { useTenantAvailability } from '@/main_app/tenant/useTenantAvailability';
import { PageLoading } from '@/shared/components/PageLoading';
import { useErrorQuery } from '@/shared/routing/useErrorQuery';
import { decideAppLoginAccess } from './guard';
import { useAppAuth, useUrlTenantCode } from './useAppAuth';

export const AppLoginRoute = () => {
    const tenant_code = useUrlTenantCode();
    const { state, logout } = useAppAuth();
    const decision = decideAppLoginAccess(state, tenant_code);
    switch (decision.type) {
        case 'loading':
            return <PageLoading />;
        case 'redirect_home':
            return <Navigate to={appHomePath(tenant_code)} replace />;
        case 'tenant_mismatch':
            return <TenantErrorPage kind="mismatch" tenant_code={tenant_code} session_tenant_code={decision.session_tenant_code} onLogout={logout} />;
        case 'error':
            throw decision.error;
        default:
            return <AppLoginWithTenantCheck tenant_code={tenant_code} />;
    }
};

/**
 * テナントの利用可否を確認してからログイン画面を出すコンポーネント
 * 未認証のときだけ存在確認 API を呼ぶため (レート制限の対象)、AppLoginRoute から分けている。
 */
const AppLoginWithTenantCheck = ({ tenant_code }: { tenant_code: string }) => {
    const { result } = useTenantAvailability(tenant_code);
    const { login } = useAppAuth();
    const error_code = useErrorQuery();
    if (result.status === 'loading') return <PageLoading />;
    if (result.status === 'error') throw result.error;
    if (result.value !== 'active') return <TenantErrorPage kind={result.value} tenant_code={tenant_code} />;
    return <AppLoginPage tenant_code={tenant_code} error_code={error_code} onLogin={() => login(tenant_code)} />;
};

export default AppLoginRoute;
