// AP の認証後レイアウトで使う表示用の定義 (ナビゲーション項目・ロールの表示名)
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ChecklistIcon from '@mui/icons-material/Checklist';
import HomeIcon from '@mui/icons-material/Home';
import PeopleIcon from '@mui/icons-material/People';
import { appHomePath, appOrganizationsPath, appProfilePath, appTodosPath, appUsersPath } from '@/main_app/paths';
import type { NavItem } from '@/shared/layouts/AppShell/nav_item';

/**
 * AP のナビゲーション項目を返す関数
 * 画面が未実装の項目は to を null にする (準備中の表示)。実装したら、画面のパスを paths.ts に足して to に渡す。
 * @param {string} tenant_code テナントコード
 * @returns {NavItem[]} ナビゲーション項目
*/
export const appNavItemsOf = (tenant_code: string): NavItem[] => [
    { id: 'home', label: 'ホーム', to: appHomePath(tenant_code), end: true, icon: <HomeIcon /> },
    { id: 'users', label: 'ユーザー管理', to: appUsersPath(tenant_code), icon: <PeopleIcon /> },
    { id: 'organizations', label: '組織管理', to: appOrganizationsPath(tenant_code), icon: <AccountTreeIcon /> },
    { id: 'profile', label: 'プロフィール', to: appProfilePath(tenant_code), icon: <AccountCircleIcon /> },
    { id: 'todo', label: 'ToDo', to: appTodosPath(tenant_code), icon: <ChecklistIcon /> },
];

/** AP のロール (01 §7.5) の表示名 */
export const APP_ROLE_LABELS: Readonly<Record<string, string>> = {
    tenant_admin: 'テナント管理者',
    member: 'メンバー',
};

/**
 * ロールの一覧を表示名にする関数 (一覧に無いロールはそのまま、無ければ空配列)
 * @param {string[]} roles ロール
 * @returns {string[]} 表示名
*/
export const appRoleLabelsOf = (roles: string[]): string[] => roles.map((role) => (Object.hasOwn(APP_ROLE_LABELS, role) ? APP_ROLE_LABELS[role] : role));

/**
 * ヘッダーに出す主なロールの表示名を返す関数 (強いロールを優先する。tenant_admin と member の両方を持てば「テナント管理者」)
 * @param {string[]} roles ロール
 * @returns {string | undefined} 表示名 (既知のロールを持たなければ undefined)
*/
export const appPrimaryRoleLabelOf = (roles: string[]): string | undefined => {
    const role = Object.keys(APP_ROLE_LABELS).find((key) => roles.includes(key));
    return role === undefined ? undefined : APP_ROLE_LABELS[role];
};
