/**
 * @desc トップレベルのルートツリー (01 §11.1)
 *
 *   /               ランディング (テナントコード入力 → /{tenant_code}/login)
 *   /cp/*           コントロールプレーン (control_plane_app/routes.tsx を遅延読み込み)
 *   /{予約語}/*      NotFound (開発用ルート /dev-login・/link は開発モードのみ別途登録)
 *   /:tenantCode/*  アプリケーションプレーン (main_app/routes.tsx を遅延読み込み)
 *
 * 静的ルート (/、/cp/*、予約語) は /:tenantCode/* より先に定義する。React Router は静的セグメントを
 * 動的セグメントより優先して照合するため、定義順に依らず静的ルートが選ばれる。
 * 各プレーンは React.lazy で読み込み、片方のバンドルを読み込まずに動作させる (01 §11.2)。
 */
import { lazy, Suspense, type ReactNode } from 'react';
import type { RouteObject } from 'react-router-dom';
import { CP_SEGMENT } from '@/control_plane_app/paths';
import { PageLoading } from '@/shared/components/PageLoading';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { RouteErrorBoundary } from '@/shared/routing/RouteErrorBoundary';
import { RESERVED_TENANT_CODES } from '@/shared/tenant_code';

const LandingPage = lazy(() => import('@/main_app/pages/Landing'));
const MainAppRoutes = lazy(() => import('@/main_app/routes'));
const ControlPlaneRoutes = lazy(() => import('@/control_plane_app/routes'));

/** 遅延読み込みの境界 */
const PlaneSuspense = ({ children }: { children: ReactNode }) => <Suspense fallback={<PageLoading />}>{children}</Suspense>;

export type RootRouteOptions = {
    /**
     * 開発用ルート (/dev-login、/link)。第 1 セグメントが予約語であること。
     * 本番ビルドでバンドルから除去するため、呼び出し側 (AppRoutes.tsx) で import.meta.env.MODE により出し分けて渡す。
     */
    dev_routes?: RouteObject[];
};

/**
 * ルートの第 1 セグメントを返す関数
 * @param {RouteObject} route ルート
 * @returns {string} 第 1 セグメント (path が無ければ空文字)
*/
export const firstSegmentOf = (route: RouteObject): string => (route.path ?? '').replace(/^\//, '').split('/')[0];

/**
 * 予約語のうち、他の静的ルートに使われていないものを NotFound にするルートを生成する関数
 * @param {ReadonlySet<string>} used_segments 他の静的ルートが使っている第 1 セグメント
 * @returns {RouteObject[]} ルート
*/
export const createReservedRoutes = (used_segments: ReadonlySet<string>): RouteObject[] => {
    return [...RESERVED_TENANT_CODES]
        .filter((segment) => !used_segments.has(segment))
        .map((segment) => ({ id: `reserved:${segment}`, path: `${segment}/*`, element: <NotFoundPage /> }));
};

/**
 * トップレベルのルートツリーを生成する関数
 * @param {RootRouteOptions} options オプション
 * @returns {RouteObject[]} ルートツリー (createBrowserRouter / createMemoryRouter に渡す)
*/
export const createRootRoutes = ({ dev_routes = [] }: RootRouteOptions = {}): RouteObject[] => {
    const used_segments = new Set([CP_SEGMENT, ...dev_routes.map(firstSegmentOf)]);
    return [{
        id: 'root',
        ErrorBoundary: RouteErrorBoundary,
        children: [
            { id: 'landing', index: true, element: <PlaneSuspense><LandingPage /></PlaneSuspense> },
            { id: 'cp', path: `${CP_SEGMENT}/*`, element: <PlaneSuspense><ControlPlaneRoutes /></PlaneSuspense> },
            ...dev_routes,
            ...createReservedRoutes(used_segments),
            { id: 'app', path: ':tenantCode/*', element: <PlaneSuspense><MainAppRoutes /></PlaneSuspense> },
        ],
    }];
};

export default createRootRoutes;
