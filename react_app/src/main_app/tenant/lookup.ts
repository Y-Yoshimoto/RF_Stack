// テナントの存在確認 (公開 API `GET /api/v1/public/tenants/{tenant_code}`)
// 01 §11.1: 存在しない・利用できないテナントコードでは、この API の結果をもとにエラー画面を表示する。
import { PUBLIC_API_PATHS, type PublicTenantRead } from '@/main_app/api/contract';
import type { Requester } from '@/shared/auth/session';
import { tenantCodeViolationOf } from '@/shared/tenant_code';
import { requestFetch } from '@/utils/libs/FetchComponents/common';
import { ApiError } from '@/utils/libs/FetchComponents/problem';

/**
 * テナントの利用可否。
 * - active: ログインできる
 * - not_found: 存在しない・削除済み・形式不正・予約語 (区別しない)
 * - suspended: 停止中・削除要求中
 * - unavailable: 払い出し中・払い出し失敗・削除処理中など、それ以外の理由で利用できない
 */
export type TenantAvailability = 'active' | 'not_found' | 'suspended' | 'unavailable';

/**
 * テナントの状態から利用可否を求める関数
 * @param {PublicTenantRead['status']} status テナントの状態
 * @returns {TenantAvailability} 利用可否
*/
export const availabilityOf = (status: PublicTenantRead['status']): TenantAvailability => {
    switch (status) {
        case 'ACTIVE':
            return 'active';
        case 'SUSPENDED':
        case 'PENDING_DELETION':
            return 'suspended';
        case 'DELETED':
            return 'not_found';
        default:
            return 'unavailable';
    }
};

/**
 * テナントの利用可否を問い合わせる関数
 * 形式違反・予約語は API を呼ばずに not_found とする。404 は not_found、それ以外の失敗 (429・503・ネットワークエラー等) は例外のまま送出する。
 * @param {string} tenant_code テナントコード (URL のセグメント)
 * @param {Requester} requester HTTP リクエスト関数
 * @returns {Promise<TenantAvailability>} 利用可否
*/
export const lookupTenantAvailability = async (tenant_code: string, requester: Requester = requestFetch): Promise<TenantAvailability> => {
    if (tenantCodeViolationOf(tenant_code) !== null) return 'not_found';
    let body: PublicTenantRead | null;
    try {
        body = await requester<PublicTenantRead>({ url: PUBLIC_API_PATHS.tenant(tenant_code), method: 'GET' });
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) return 'not_found';
        throw error;
    }
    if (!body) throw new Error('テナントの存在確認の応答が空です');
    return availabilityOf(body.status);
};
