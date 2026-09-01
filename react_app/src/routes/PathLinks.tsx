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
 * @param additional_path - 追加上位のパス
 * @description
 * 開発環境向けのルーティング情報をリストにして表示するコンポーネント
 * @returns
 */
const PathLinks = ({ routes, additional_path = '' }: { routes: Array<IndexRouteObject>, additional_path?: string }) => {
  if (!routes || routes.length === 0) return <></>;
  const in_route = routes[0].children as Array<IndexRouteObject>;

  return (
    <>
      <h4>Path Links</h4>
      <ul>{in_route.map(route => PathLink({ ...route, path: `${additional_path}/${route.path}` }))}</ul>
    </>
  );
};

// PathLinkコンポーネント
// ルーティング情報をリンクアイテムとして表示するコンポーネント
const PathLink = (route: IndexRouteObject) => {
  console.log(`PathLink: ${route.path}`);
  return (<li key={route.id}><Link href={route.path}>{route.id}</Link></li>);
};

export default PathLinks;
