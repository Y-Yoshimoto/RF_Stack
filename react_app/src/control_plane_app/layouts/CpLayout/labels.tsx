// CP の認証後レイアウトで使う表示用の定義 (ナビゲーション項目・権限の表示名)
import AddBusinessIcon from '@mui/icons-material/AddBusiness';
import DashboardIcon from '@mui/icons-material/Dashboard';
import DomainIcon from '@mui/icons-material/Domain';
import type { CpPermissions } from '@/control_plane_app/auth/guard';
import { CP_HOME_PATH, CP_TENANT_CREATE_PATH, CP_TENANTS_PATH } from '@/control_plane_app/paths';
import type { NavItem } from '@/shared/layouts/AppShell/nav_item';

/**
 * CP のナビゲーション項目を返す関数
 * 変更操作の入口 (テナント作成) は、変更権限 (saas_admin) があるときだけ含める。saas_viewer には表示しない (01 §11.2。API 側でも拒否される)。
 * 画面が未実装の項目は to を null にする (準備中の表示)。
 * @param {CpPermissions} permissions CP の権限
 * @returns {NavItem[]} ナビゲーション項目
*/
export const cpNavItemsOf = (permissions: CpPermissions): NavItem[] => {
    const items: NavItem[] = [
        { id: 'dashboard', label: 'ダッシュボード', to: CP_HOME_PATH, end: true, icon: <DashboardIcon /> },
        { id: 'tenants', label: 'テナント一覧', to: CP_TENANTS_PATH, icon: <DomainIcon /> },
    ];
    if (permissions.can_write) items.push({ id: 'tenant-create', label: 'テナント作成', to: CP_TENANT_CREATE_PATH, icon: <AddBusinessIcon /> });
    return items;
};

/**
 * 権限の表示名を返す関数
 * @param {CpPermissions} permissions CP の権限
 * @returns {string} saas_admin は「SaaS 管理者」、参照のみは「閲覧専用」
*/
export const cpPermissionLabelOf = (permissions: CpPermissions): string => (permissions.can_write ? 'SaaS 管理者' : '閲覧専用');
