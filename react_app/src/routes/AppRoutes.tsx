/**
 * @desc React 各ルーティング読み込み振り分けるルーターの設定
 */

// 環境変数からベースパスを取得/未定義の場合は/を設定
const ROUTER_BASENAME = import.meta.env.VITE_APP_ROUTER_BASE || '/';
const MODE = import.meta.env.MODE || 'production';
const IS_DEVELOPMENT = MODE === 'development';

// ルーティングライブラリ
import { RouterProvider, createBrowserRouter, type RouteObject, type IndexRouteObject } from 'react-router-dom';

// ルーティング宣言リスト読み込み
import routes from './getRoutes';
// リンク生成コンポーネント
import PathLinks from './PathLinks';

// 未認証ルーティング
import uncertifiedRoutes from './uncertified';

// ルートガードコンポーネント
import { RequireAuth, RedirectIfAuthed } from './guards';

// 開発環境のみ: ルーティング情報表示ルート
const devRoutes: RouteObject[] = IS_DEVELOPMENT
  ? [{ path: '/link', id: 'loopback', element: <PathLinks routes={routes as unknown as IndexRouteObject[]} /> }]
  : [];

// ルーターを単一の安定インスタンスとして生成（再生成しない）
const router = createBrowserRouter([
  {
    // 認証済みルートグループ: 未認証の場合 /login へリダイレクト
    element: <RequireAuth />,
    children: [...routes, ...devRoutes] as RouteObject[],
  },
  {
    // 未認証ルートグループ: 認証済みの場合 /button へリダイレクト
    element: <RedirectIfAuthed />,
    children: uncertifiedRoutes as RouteObject[],
  },
], { basename: ROUTER_BASENAME });

// ルーティングコンポーネント
export const AppRoutes = () => {
  return <RouterProvider router={router} />;
};

export default AppRoutes;
