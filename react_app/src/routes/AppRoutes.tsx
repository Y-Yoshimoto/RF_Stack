/**
 * @desc トップレベルのルーター (ルートツリーは root_routes.tsx)
 */
import { RouterProvider, createBrowserRouter, type RouteObject } from 'react-router-dom';
import { createRootRoutes } from './root_routes';
import { DevLinksPage } from './dev/DevLinksPage';
import { DevLoginPage } from './dev/DevLoginPage';

// 環境変数からベースパスを取得/未定義の場合は/を設定
const ROUTER_BASENAME = import.meta.env.VITE_APP_ROUTER_BASE || '/';
// import.meta.env.MODE はビルド時に文字列へ置き換えられる。npm run build:production (MODE=production) では
// 以下の開発用ルートが定数畳み込みで除去され、DevLoginPage / DevLinksPage もバンドルに含まれない。
const IS_DEVELOPMENT = import.meta.env.MODE === 'development';

// 開発用ルート (第 1 セグメントはいずれも予約語)。
// 未認証で開くため、どのプレーンの認証ガードにも属さない。実際の防御は FastAPI 側でルート自体を登録しないことによる。
const dev_routes: RouteObject[] = IS_DEVELOPMENT
  ? [
    { id: 'dev-login', path: 'dev-login', element: <DevLoginPage /> },
    { id: 'link', path: 'link', element: <DevLinksPage /> },
  ]
  : [];

// ルーターを単一の安定インスタンスとして生成（再生成しない）
const router = createBrowserRouter(createRootRoutes({ dev_routes }), { basename: ROUTER_BASENAME });

// ルーティングコンポーネント
export const AppRoutes = () => {
  return <RouterProvider router={router} />;
};

export default AppRoutes;
