/**
 * @desc React 各ルーティング読み込み振り分けるルーターの設定
 */

// 環境変数からベースパスを取得/未定義の場合は/を設定
const ROUTER_BASENAME = import.meta.env.VITE_APP_ROUTER_BASE || '/';
const MODE = import.meta.env.MODE || 'production';
const IS_DEVELOPMENT = MODE === 'development';

// 認証コンテキスト
import { use } from 'react';
import { AuthNZContext } from '@/store/AuthNZ';

// ルーティングライブラリ
import { RouterProvider, createBrowserRouter } from 'react-router-dom';


// ルーティング宣言リスト読み込み
import routes from './getRoutes';
// リンク生成コンポーネント
import PathLinks from './PathLinks';

// 未認証ルーティング
import uncertifiedRoutes from './uncertified'

/** ルーティング設定関数
 * ルーティングを振り分けるための関数
 * @function
 * @returns {object} - ルーティングオブジェクト
 * @examples
 */
const createRouter = (authStatus) => {
  // 開発環境の場合、ルーティング情報を表示するルートを生成
  const linkroute = IS_DEVELOPMENT
    ? [{ path: '/link', id: 'loopback', element: <PathLinks routes={routes} /> }]
    : [];

  // ルーティングオブジェクト生成
  //// 認証されていない場合は未認証ルートを返す
  if (!authStatus.isAuthN) {
    return createBrowserRouter([...uncertifiedRoutes], { basename: ROUTER_BASENAME });
  }
  return createBrowserRouter([...routes, ...linkroute], { basename: ROUTER_BASENAME });
};

// ルーティングコンポーネント
export const AppRoutes = () => {
  const { authStatus } = use(AuthNZContext);

  return (
    <>
      <RouterProvider router={createRouter(authStatus)} />
    </>
  );
};

export default AppRoutes;
