/**
 * @desc CP のログイン画面 (`/cp/login`) のルート
 * 権限のある CP セッションならホームへ。未認証 (または権限の無いセッション) ならログイン画面を出す。
 */
import { Navigate } from 'react-router-dom';
import { CpLoginPage } from '@/control_plane_app/pages/Login';
import { CP_HOME_PATH } from '@/control_plane_app/paths';
import { PageLoading } from '@/shared/components/PageLoading';
import { useErrorQuery } from '@/shared/routing/useErrorQuery';
import { decideCpLoginAccess } from './guard';
import { useCpAuth } from './useCpAuth';

export const CpLoginRoute = () => {
    const { state, login } = useCpAuth();
    const error_code = useErrorQuery();
    const decision = decideCpLoginAccess(state);
    switch (decision.type) {
        case 'loading':
            return <PageLoading />;
        case 'redirect_home':
            return <Navigate to={CP_HOME_PATH} replace />;
        case 'error':
            throw decision.error;
        default:
            return <CpLoginPage error_code={error_code} onLogin={login} />;
    }
};

export default CpLoginRoute;
