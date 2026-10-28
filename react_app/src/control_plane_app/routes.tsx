/**
 * @desc コントロールプレーン (CP) のルートツリー (`/cp/*`)
 * トップレベルのルーター (routes/root_routes.tsx) から React.lazy で遅延読み込みされる (02 §6.1)。
 * 認証状態 (ControlPlaneAuthProvider) はこのツリーの中だけに置き、AP とは別インスタンスにする (01 §11.2)。
 *
 *   /cp/login  ログイン
 *   /cp/       ホーム (認証後。saas_admin / saas_viewer)
 *   /cp/*      未定義 (認証後に NotFound)
 */
import { Route, Routes } from 'react-router-dom';
import { ControlPlaneAuthProvider } from '@/control_plane_app/auth/ControlPlaneAuthProvider';
import { CpLoginRoute } from '@/control_plane_app/auth/CpLoginRoute';
import { RequireCpSession } from '@/control_plane_app/auth/RequireCpSession';
import { CpLayout } from '@/control_plane_app/layouts/CpLayout';
import { CpHomePage } from '@/control_plane_app/pages/Home';
import { CP_HOME_PATH, CP_ROUTE } from '@/control_plane_app/paths';
import { AuthLayout } from '@/shared/layouts/AuthLayout';
import { NotFoundPage } from '@/shared/pages/NotFound';

export const ControlPlaneRoutes = () => {
    return (
        <ControlPlaneAuthProvider>
            <Routes>
                <Route element={<AuthLayout />}>
                    <Route path={CP_ROUTE.LOGIN} element={<CpLoginRoute />} />
                </Route>
                <Route element={<RequireCpSession />}>
                    {/* 認証後の画面は共通のレイアウト (ヘッダー・ナビゲーション) の中に表示する。レイアウトが <main> を持つため NotFound は embedded */}
                    <Route element={<CpLayout />}>
                        <Route index element={<CpHomePage />} />
                        <Route path="*" element={<NotFoundPage embedded home_path={CP_HOME_PATH} home_label="ダッシュボードへ戻る" />} />
                    </Route>
                </Route>
            </Routes>
        </ControlPlaneAuthProvider>
    );
};

export default ControlPlaneRoutes;
