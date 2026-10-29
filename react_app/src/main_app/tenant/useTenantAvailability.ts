/**
 * @description:
 * テナントの利用可否を問い合わせるカスタムフック (AP のログイン画面で使う)
*/
import { useAsyncValue, type AsyncResult } from '@/shared/hooks/useAsyncValue';
import { lookupTenantAvailability, type TenantAvailability } from './lookup';

/**
 * テナントの利用可否を問い合わせるカスタムフック
 * テナントコードが変わると再問い合わせする。
 * @param {string} tenant_code テナントコード
 * @param {(tenant_code: string) => Promise<TenantAvailability>} lookup 問い合わせ関数 (テスト用に差し替え可能)
 * @returns {{ result: AsyncResult<TenantAvailability>, reload: () => void }} 結果と再問い合わせ関数
*/
export const useTenantAvailability = (
    tenant_code: string,
    lookup: (tenant_code: string) => Promise<TenantAvailability> = lookupTenantAvailability,
): { result: AsyncResult<TenantAvailability>; reload: () => void } => {
    return useAsyncValue(() => lookup(tenant_code), `tenant:${tenant_code}`);
};

export default useTenantAvailability;
