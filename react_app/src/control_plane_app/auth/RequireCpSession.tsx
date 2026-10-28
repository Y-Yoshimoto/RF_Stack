/**
 * @desc CP の認証後画面のルートガード
 * 「CP セッションが認証済み」かつ saas_admin / saas_viewer のときだけ子ルートを表示する (01 §11.2)。
 * - 未認証: `/cp/login` へリダイレクト
 * - ロール不足: `/cp/login?error=login_rejected` へリダイレクト
 * - 状態の取得失敗 (401 以外): 例外を送出し、ルートのエラーバウンダリーに任せる
 */
import { Navigate, Outlet } from 'react-router-dom';
import { CP_LOGIN_PATH } from '@/control_plane_app/paths';
import { PageLoading } from '@/shared/components/PageLoading';
import { LOGIN_ERROR_CODE } from '@/shared/auth/type';
import { ERROR_QUERY_PARAM } from '@/shared/routing/useErrorQuery';
import { decideCpAccess } from './guard';
import { useCpAuth } from './useCpAuth';

/** ロール不足のときの遷移先 */
export const CP_FORBIDDEN_PATH = `${CP_LOGIN_PATH}?${new URLSearchParams({ [ERROR_QUERY_PARAM]: LOGIN_ERROR_CODE.LOGIN_REJECTED }).toString()}`;

export const RequireCpSession = () => {
    const { state } = useCpAuth();
    const decision = decideCpAccess(state);
    switch (decision.type) {
        case 'loading':
            return <PageLoading />;
        case 'redirect_login':
            return <Navigate to={CP_LOGIN_PATH} replace />;
        case 'forbidden':
            return <Navigate to={CP_FORBIDDEN_PATH} replace />;
        case 'error':
            throw decision.error;
        default:
            return <Outlet />;
    }
};

export default RequireCpSession;
