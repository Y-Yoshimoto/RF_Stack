// コントロールプレーン (CP) のセッション (BFF `/api/auth/cp/*`)
import { AUTH_API } from '@/constants.ts';
import { assignLocation, fetchAuthStatus, type AssignLocation, type Requester } from '@/shared/auth/session';
import type { AuthStatusUser } from '@/shared/auth/type';
import { requestFetch } from '@/utils/libs/FetchComponents/common';

/**
 * CP のセッション。
 */
export type CpSession = {
    /** ユーザー。roles は saas_admin / saas_viewer。 */
    user: AuthStatusUser;
};

/**
 * CP のセッションを読み込む関数
 * @param {Requester} requester HTTP リクエスト関数
 * @returns {Promise<CpSession | null>} 認証済みならセッション、未認証 (401) なら null。それ以外の失敗は例外
*/
export const loadCpSession = async (requester: Requester = requestFetch): Promise<CpSession | null> => {
    const body = await fetchAuthStatus(AUTH_API.CP_STATUS, requester);
    if (body === null) return null;
    if (body.plane !== 'cp') throw new Error('CP の認証ステータスのプレーンが cp ではありません');
    return { user: body.user };
};

/**
 * CP のログインを開始する関数 (BFF のログイン開始 API へトップレベル遷移する)
 * @param {AssignLocation} assign トップレベル遷移関数
*/
export const startCpLogin = (assign: AssignLocation = assignLocation): void => {
    assign(AUTH_API.CP_LOGIN);
};
