// CP のルートガードの判定と権限 (純粋関数)
// 01 §11.2: CP のルートガードは「CP セッションが認証済み」かつ saas_admin または saas_viewer を確認する。
// saas_viewer には変更操作の UI を表示しない (API 側でも 403 で拒否される)。
import type { SessionState } from '@/shared/auth/type';
import type { CpSession } from './session';

/** CP のロール (01 §7.5) */
export const CP_ROLE = {
    ADMIN: 'saas_admin',
    VIEWER: 'saas_viewer',
} as const;

/**
 * CP の権限 (画面の出し分け用。保護は API 側で行う)。
 */
export type CpPermissions = {
    /** saas_admin を持つ。 */
    is_admin: boolean;
    /** saas_viewer のみ (参照のみ。saas_admin を持たない)。 */
    is_viewer: boolean;
    /** 参照系 (一覧・詳細・メトリクス) を使える。 */
    can_read: boolean;
    /** 変更系 (作成・再実行・停止・再開・削除) を使える。 */
    can_write: boolean;
};

/**
 * ロールから CP の権限を求める関数
 * @param {readonly string[]} roles ロール
 * @returns {CpPermissions} 権限
*/
export const cpPermissionsOf = (roles: readonly string[]): CpPermissions => {
    const is_admin = roles.includes(CP_ROLE.ADMIN);
    const has_viewer = roles.includes(CP_ROLE.VIEWER);
    return { is_admin, is_viewer: has_viewer && !is_admin, can_read: is_admin || has_viewer, can_write: is_admin };
};

/** 権限なし (未認証など) */
export const NO_CP_PERMISSIONS: CpPermissions = { is_admin: false, is_viewer: false, can_read: false, can_write: false };

/**
 * 認証後の CP 画面に対する判定。
 * forbidden は CP セッションはあるが saas_admin / saas_viewer のどちらも持たないことを表す。
 */
export type CpAccessDecision =
    | { type: 'loading' }
    | { type: 'allow'; session: CpSession }
    | { type: 'redirect_login' }
    | { type: 'forbidden' }
    | { type: 'error'; error: unknown };

/**
 * 認証後の CP 画面 (`/cp/*`) に入れるかを判定する関数
 * @param {SessionState<CpSession>} state CP のセッションの状態
 * @returns {CpAccessDecision} 判定
*/
export const decideCpAccess = (state: SessionState<CpSession>): CpAccessDecision => {
    switch (state.status) {
        case 'loading':
            return { type: 'loading' };
        case 'error':
            return { type: 'error', error: state.error };
        case 'unauthenticated':
            return { type: 'redirect_login' };
    }
    if (!cpPermissionsOf(state.session.user.roles).can_read) return { type: 'forbidden' };
    return { type: 'allow', session: state.session };
};

/**
 * CP のログイン画面に対する判定。
 */
export type CpLoginDecision =
    | { type: 'loading' }
    | { type: 'redirect_home' }
    | { type: 'show_login' }
    | { type: 'error'; error: unknown };

/**
 * CP のログイン画面 (`/cp/login`) の判定をする関数
 * 権限のある CP セッションならホームへ。未認証、または権限の無いセッションならログイン画面を出す (ホームとの往復を防ぐ)。
 * @param {SessionState<CpSession>} state CP のセッションの状態
 * @returns {CpLoginDecision} 判定
*/
export const decideCpLoginAccess = (state: SessionState<CpSession>): CpLoginDecision => {
    const decision = decideCpAccess(state);
    switch (decision.type) {
        case 'loading':
        case 'error':
            return decision;
        case 'allow':
            return { type: 'redirect_home' };
        default:
            return { type: 'show_login' };
    }
};
