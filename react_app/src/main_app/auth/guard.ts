// AP のルートガードの判定 (純粋関数)。画面の出し分けは RequireAppSession / AppLoginRoute が行う。
// 01 §11.2: AP のルートガードは「AP セッションが認証済み」かつ「セッションのテナントコード = URL のテナントコード」を確認する。
import type { SessionState } from '@/shared/auth/type';
import type { AppSession } from './session';

/**
 * AP の API が 403 を返したことで分かった、テナントを利用できない理由。
 * - suspended: 停止中・削除要求中 (Problem Details の code: tenant_inactive)
 * - unavailable: それ以外 (code: tenant_unavailable。存在有無を推測させないため集約されている)
 */
export type TenantBlockReason = 'suspended' | 'unavailable';

/**
 * 認証後の AP 画面に対する判定。
 */
export type AppAccessDecision =
    | { type: 'loading' }
    | { type: 'allow'; session: AppSession }
    | { type: 'redirect_login' }
    | { type: 'tenant_mismatch'; session_tenant_code: string }
    | { type: 'tenant_blocked'; reason: TenantBlockReason }
    | { type: 'error'; error: unknown };

/**
 * 認証後の AP 画面 (`/:tenantCode/*`) に入れるかを判定する関数
 * @param {SessionState<AppSession>} state AP のセッションの状態
 * @param {string} url_tenant_code URL のテナントコード
 * @param {TenantBlockReason | null} blocked API の 403 で分かったテナントの利用不可 (無ければ null)
 * @returns {AppAccessDecision} 判定
*/
export const decideAppAccess = (state: SessionState<AppSession>, url_tenant_code: string, blocked: TenantBlockReason | null = null): AppAccessDecision => {
    switch (state.status) {
        case 'loading':
            return { type: 'loading' };
        case 'error':
            return { type: 'error', error: state.error };
        case 'unauthenticated':
            return { type: 'redirect_login' };
    }
    if (state.session.tenant_code !== url_tenant_code) return { type: 'tenant_mismatch', session_tenant_code: state.session.tenant_code };
    if (blocked !== null) return { type: 'tenant_blocked', reason: blocked };
    return { type: 'allow', session: state.session };
};

/**
 * AP のログイン画面に対する判定。
 * check_tenant はログイン画面を出す前にテナントの存在確認を行うことを表す。
 */
export type AppLoginDecision =
    | { type: 'loading' }
    | { type: 'redirect_home' }
    | { type: 'tenant_mismatch'; session_tenant_code: string }
    | { type: 'check_tenant' }
    | { type: 'error'; error: unknown };

/**
 * AP のログイン画面 (`/:tenantCode/login`) の判定をする関数
 * 同じテナントで認証済みならホームへ、別テナントで認証済みなら「別テナントでログイン中」、未認証ならテナントの存在確認へ進む。
 * @param {SessionState<AppSession>} state AP のセッションの状態
 * @param {string} url_tenant_code URL のテナントコード
 * @returns {AppLoginDecision} 判定
*/
export const decideAppLoginAccess = (state: SessionState<AppSession>, url_tenant_code: string): AppLoginDecision => {
    switch (state.status) {
        case 'loading':
            return { type: 'loading' };
        case 'error':
            return { type: 'error', error: state.error };
        case 'unauthenticated':
            return { type: 'check_tenant' };
    }
    if (state.session.tenant_code !== url_tenant_code) return { type: 'tenant_mismatch', session_tenant_code: state.session.tenant_code };
    return { type: 'redirect_home' };
};
