// アプリケーションプレーン (AP) のセッション (BFF `/api/auth/app/*`)
import { AUTH_API } from '@/constants.ts';
import { assignLocation, fetchAuthStatus, type AssignLocation, type Requester } from '@/shared/auth/session';
import type { AuthStatusUser } from '@/shared/auth/type';
import { requestFetch } from '@/utils/libs/FetchComponents/common';

/**
 * AP のセッション (ブラウザあたり 1 テナント。01 §7.2)。
 */
export type AppSession = {
    /** ログイン中のテナントコード。ルートガードで URL のテナントコードと照合する。 */
    tenant_code: string;
    /** ユーザー。roles は tenant_admin / member。 */
    user: AuthStatusUser;
};

/**
 * AP のセッションを読み込む関数
 * @param {Requester} requester HTTP リクエスト関数
 * @returns {Promise<AppSession | null>} 認証済みならセッション、未認証 (401) なら null。それ以外の失敗は例外
*/
export const loadAppSession = async (requester: Requester = requestFetch): Promise<AppSession | null> => {
    const body = await fetchAuthStatus(AUTH_API.APP_STATUS, requester);
    if (body === null) return null;
    // 別プレーンの応答・tenant_code の欠落は契約違反として握り潰さず失敗にする
    if (body.plane !== 'app' || !body.tenant_code) throw new Error('AP の認証ステータスではないか、tenant_code がありません');
    return { tenant_code: body.tenant_code, user: body.user };
};

/**
 * AP のログイン開始 URL を返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/api/auth/app/login?tenant_code=...`
*/
export const appLoginUrl = (tenant_code: string): string => `${AUTH_API.APP_LOGIN}?${new URLSearchParams({ tenant_code }).toString()}`;

/**
 * AP のログインを開始する関数 (BFF のログイン開始 API へトップレベル遷移する)
 * @param {string} tenant_code テナントコード
 * @param {AssignLocation} assign トップレベル遷移関数
*/
export const startAppLogin = (tenant_code: string, assign: AssignLocation = assignLocation): void => {
    assign(appLoginUrl(tenant_code));
};
