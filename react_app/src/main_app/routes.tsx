/**
 * @desc アプリケーションプレーン (AP) のルートツリー (`/:tenantCode/*`)
 * トップレベルのルーター (routes/root_routes.tsx) から React.lazy で遅延読み込みされる (02 §6.1)。
 * 認証状態 (AppAuthProvider) はこのツリーの中だけに置き、CP とは別インスタンスにする (01 §11.2)。
 *
 *   /:tenantCode/login     ログイン (テナントの存在確認 → ログイン開始)
 *   /:tenantCode/          ホーム (認証後)
 *   /:tenantCode/sample/*  サンプル画面 (認証後。基盤の実装が進んだ段階で削除する)
 *   /:tenantCode/*         未定義 (認証後に NotFound)
 *
 * URL のテナントコードが形式違反・予約語の場合は、API を呼ばずにテナント不在のエラー画面を出す。
 */
import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppAuthProvider } from '@/main_app/auth/AppAuthProvider';
import { AppLoginRoute } from '@/main_app/auth/AppLoginRoute';
import { RequireAppSession } from '@/main_app/auth/RequireAppSession';
import { useUrlTenantCode } from '@/main_app/auth/useAppAuth';
import { AppLayout } from '@/main_app/layouts/AppLayout';
import { AppHomePage } from '@/main_app/pages/Home';
import { TenantErrorPage } from '@/main_app/pages/TenantError';
import { APP_ROUTE, appHomePath } from '@/main_app/paths';
import { PageLoading } from '@/shared/components/PageLoading';
import { AuthLayout } from '@/shared/layouts/AuthLayout';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { tenantCodeViolationOf } from '@/shared/tenant_code';

// サンプル画面は AP の中でもさらに遅延読み込みする
const SampleRoutes = lazy(() => import('@/sample/routes'));

export const MainAppRoutes = () => {
    const tenant_code = useUrlTenantCode();
    if (tenantCodeViolationOf(tenant_code) !== null) return <TenantErrorPage kind="not_found" tenant_code={tenant_code} />;
    return (
        <AppAuthProvider>
            <Routes>
                <Route element={<AuthLayout />}>
                    <Route path={APP_ROUTE.LOGIN} element={<AppLoginRoute />} />
                </Route>
                <Route element={<RequireAppSession />}>
                    {/* 認証後の画面は共通のレイアウト (ヘッダー・ナビゲーション) の中に表示する。レイアウトが <main> を持つため NotFound は embedded */}
                    <Route element={<AppLayout />}>
                        <Route index element={<AppHomePage />} />
                        <Route path={APP_ROUTE.SAMPLE} element={<Suspense fallback={<PageLoading />}><SampleRoutes /></Suspense>} />
                        <Route path="*" element={<NotFoundPage embedded home_path={appHomePath(tenant_code)} home_label="ホームへ戻る" />} />
                    </Route>
                </Route>
            </Routes>
        </AppAuthProvider>
    );
};

export default MainAppRoutes;
