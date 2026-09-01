/**
 * ページルーティング
 */
import { Navigate, Outlet } from 'react-router-dom';
// コンポーネント読み込み
import ButtonPage from '@/sample/pages/ButtonPage';
import FetchPage from '@/sample/pages/FetchPage';
import IndexedDBPage from '@/sample/pages/IndexdDBPage';
import LeyoutChildren from '@/sample/pages/LeyoutChildren';
import ErrorPage from '@/sample/pages/ErrorPage';

import FetchLoaderPage from '@/sample/pages/FetchPage/FetchLoder';
import loader_FetchLoaderPage from '@/sample/pages/FetchPage/FetchLoder/loader';

import FetchUse from '@/sample/pages/FetchPage/FetchUse';

import { WErrorBoundaryRouter } from '@/utils/libs/WrapperComponents/ErrorBoundary';

/**
 * ルーティングの設定関数
 * @function
 * @param {Object} props - React props
 * @returns {list} ルーティングリスト
 */
const routes_list = [
  { path: 'button', id: 'button', element: <ButtonPage /> },
  { path: 'fetch', id: 'fetch', element: <FetchPage /> },
  {
    path: 'fetch-loader/:key', id: 'fetch-loader', element: <FetchLoaderPage />,
    loader: loader_FetchLoaderPage
  },
  { path: 'fetch-use', id: 'fetch-use', element: <FetchUse /> },
  { path: 'indexedDB', id: 'indexedDB', element: <IndexedDBPage /> },
  { path: 'layoutChildren', id: 'layout-children', element: <LeyoutChildren /> },
  { path: 'error', id: 'error', element: <ErrorPage />, ErrorBoundary: WErrorBoundaryRouter },
  { path: '*', id: 'not-found', element: <Navigate to={'/button'} replace /> }
];

// DataRouteObjectの型定義に従い、ルーティング設定を行う
// https://api.reactrouter.com/v7/interfaces/react_router.IndexRouteObject.html#ErrorBoundary
const routes = [{
  id: 'root',
  path: "/",
  element: <><Outlet /></>,
  ErrorBoundary: WErrorBoundaryRouter,
  children: routes_list,
  // クライアントサイド用のHydrateFallbacの設定
  HydrateFallback: () => null,
}];

export default routes;
