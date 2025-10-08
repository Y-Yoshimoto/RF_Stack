/** 
 * PathLinks.tsx
 * 開発環境向けのルーティング情報を表示するコンポーネント
 */
// インポート
import Link from '@mui/material/Link';
import { IndexRouteObject } from 'react-router';

/**
 * PathLinksコンポーネント
 * @param routes - ルーティング情報の配列
 * @param routes.path - ルートのパス
 * @param routes.id - ルートのID
 * @param routes.element - ルートの要素
 * @param additionalPath - 追加上位のパス
 * @description
 * 開発環境向けのルーティング情報をリストにして表示するコンポーネント
 * @returns 
 */
const PathLinks = ({ routes, additionalPath = '' }: { routes: Array<IndexRouteObject>, additionalPath?: string }) => {
  if (!routes || routes.length === 0) return <></>;
  const inRoute = routes[0].children as Array<IndexRouteObject>;

  return (
    <>
      <h4>Path Links</h4>
      <ul>{inRoute.map(route => _PathLink({ ...route, path: `${additionalPath}/${route.path}` }))}</ul>
    </>
  );
};

// _PathLinkコンポーネント
// ルーティング情報をリンクアイテムとして表示するコンポーネント
const _PathLink = (route: IndexRouteObject) => {
  console.log(`_PathLink: ${route.path}`);
  return (<li key={route.id}><Link href={route.path}>{route.id}</Link></li>);
};

export default PathLinks;
