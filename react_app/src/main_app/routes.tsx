/**
 * @desc アプリケーションプレーン (AP) のルートツリー (`/:tenantCode/*`)
 * トップレベルのルーター (routes/root_routes.tsx) から React.lazy で遅延読み込みされる (02 §6.1)。
 * 認証状態 (AppAuthProvider) はこのツリーの中だけに置き、CP とは別インスタンスにする (01 §11.2)。
 *
 *   /:tenantCode/login     ログイン (テナントの存在確認 → ログイン開始)
 *   /:tenantCode/          ホーム (認証後)
 *   /:tenantCode/users, users/new, users/:userId   ユーザー管理 (一覧・作成・詳細/編集)
 *   /:tenantCode/organizations, organizations/:organizationId   組織管理 (一覧・詳細/編集)
 *   /:tenantCode/profile   プロフィール
 *   /:tenantCode/todos, todos/new, todos/:todoId   ToDo (一覧・作成・詳細/編集)
 *   /:tenantCode/*         未定義 (認証後に NotFound)
 *
 * URL のテナントコードが形式違反・予約語の場合は、API を呼ばずにテナント不在のエラー画面を出す。
 * サンプル画面 (src/sample/) はアプリに登録しない参考用のコードのため、ここから読み込まない (02 §6.1)。
 */
import { Route, Routes } from 'react-router-dom';
import { AppAuthProvider } from '@/main_app/auth/AppAuthProvider';
import { AppLoginRoute } from '@/main_app/auth/AppLoginRoute';
import { RequireAppSession } from '@/main_app/auth/RequireAppSession';
import { useUrlTenantCode } from '@/main_app/auth/useAppAuth';
import { AppLayout } from '@/main_app/layouts/AppLayout';
import { AppHomePage } from '@/main_app/pages/Home';
import { AppOrganizationDetailPage } from '@/main_app/pages/OrganizationDetail';
import { AppOrganizationListPage } from '@/main_app/pages/OrganizationList';
import { AppProfilePage } from '@/main_app/pages/Profile';
import { TenantErrorPage } from '@/main_app/pages/TenantError';
import { AppTodoCreatePage } from '@/main_app/pages/TodoCreate';
import { AppTodoDetailPage } from '@/main_app/pages/TodoDetail';
import { AppTodoListPage } from '@/main_app/pages/TodoList';
import { AppUserCreatePage } from '@/main_app/pages/UserCreate';
import { AppUserDetailPage } from '@/main_app/pages/UserDetail';
import { AppUserListPage } from '@/main_app/pages/UserList';
import { APP_ROUTE, appHomePath } from '@/main_app/paths';
import { AuthLayout } from '@/shared/layouts/AuthLayout';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { tenantCodeViolationOf } from '@/shared/tenant_code';

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
                        <Route path={APP_ROUTE.USERS} element={<AppUserListPage />} />
                        <Route path={APP_ROUTE.USER_NEW} element={<AppUserCreatePage />} />
                        <Route path={APP_ROUTE.USER} element={<AppUserDetailPage />} />
                        <Route path={APP_ROUTE.ORGANIZATIONS} element={<AppOrganizationListPage />} />
                        <Route path={APP_ROUTE.ORGANIZATION} element={<AppOrganizationDetailPage />} />
                        <Route path={APP_ROUTE.PROFILE} element={<AppProfilePage />} />
                        <Route path={APP_ROUTE.TODOS} element={<AppTodoListPage />} />
                        <Route path={APP_ROUTE.TODO_NEW} element={<AppTodoCreatePage />} />
                        <Route path={APP_ROUTE.TODO} element={<AppTodoDetailPage />} />
                        <Route path="*" element={<NotFoundPage embedded home_path={appHomePath(tenant_code)} home_label="ホームへ戻る" />} />
                    </Route>
                </Route>
            </Routes>
        </AppAuthProvider>
    );
};

export default MainAppRoutes;
