/**
 * @desc React 各ルーティング読み込み振り分けるルーターの設定
 */

// 環境変数からベースパスを取得/未定義の場合は/を設定
const ROUTER_BASENAME = import.meta.env.VITE_APP_ROUTER_BASE || '/';
const MODE = import.meta.env.MODE || 'production';
const IS_DEVELOPMENT = MODE === 'development';

// ルーティングライブラリ
import { RouterProvider, createBrowserRouter } from 'react-router-dom';


// ルーティング宣言リスト読み込み
import routes from './getRoutes';
// リンク生成コンポーネント
import PathLinks from './PathLinks';

/** ルーティング設定関数
 * ルーティングを振り分けるための関数
 * @function
 * @returns {object} - ルーティングオブジェクト
 * @examples
 */
const createRouter = () => {
  // 開発環境の場合、ルーティング情報を表示するルートを生成
  const linkroute = IS_DEVELOPMENT
    ? [{ path: '/link', id: 'loopback', element: <PathLinks routes={routes} /> }]
    : [];

  // ルーティングオブジェクト生成
  return createBrowserRouter([...routes, ...linkroute], { basename: ROUTER_BASENAME });
};

// ルーティングコンポーネント
export const AppRoutes = () => {
  return (
    <>
      <RouterProvider router={createRouter()} />
    </>
  );
};

export default AppRoutes;
