// AP の権限 (純粋関数。画面の出し分けとフックの事前確認に使う。保護は API 側で行う)
// 01 §7.5: 参照 (プロフィール・ユーザー一覧・組織一覧) は tenant_admin / member、
// ユーザーの作成・更新、組織の作成・編集・削除・メンバー管理は tenant_admin のみ。
import { APP_ROLE } from '@/main_app/api/contract';

/**
 * AP の権限。
 */
export type AppPermissions = {
    /** tenant_admin を持つ。 */
    is_tenant_admin: boolean;
    /** 変更系 (ユーザー・組織の作成・更新・削除・メンバー管理) を使える。false のとき画面は変更操作の UI を表示しない。 */
    can_write: boolean;
};

/**
 * ロールから AP の権限を求める関数
 * @param {readonly string[]} roles ロール (AP セッションの user.roles)
 * @returns {AppPermissions} 権限
*/
export const appPermissionsOf = (roles: readonly string[]): AppPermissions => {
    const is_tenant_admin = roles.includes(APP_ROLE.TENANT_ADMIN);
    return { is_tenant_admin, can_write: is_tenant_admin };
};

/** 権限なし (未認証・読み込み中など) */
export const NO_APP_PERMISSIONS: AppPermissions = { is_tenant_admin: false, can_write: false };
