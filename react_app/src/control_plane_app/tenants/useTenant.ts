/**
 * @description:
 * CP のテナント詳細 (払い出し履歴を含む) と ETag を取得・保持するカスタムフック
 * 保持している ETag は useTenantActions の停止・再開・削除要求の If-Match に渡す。
*/
import { useCpApiClient } from '@/control_plane_app/api/client';
import type { TenantDetail } from '@/control_plane_app/api/contract';
import { classifyCpError, type CpErrorInfo } from '@/control_plane_app/api/errors';
import { fetchTenant, type TenantVersioned, type WithEtag } from '@/control_plane_app/api/tenants';
import { useVersionedResource } from '@/shared/hooks/useVersionedResource';

/**
 * テナント詳細の状態と操作。
 */
export type TenantDetailState = {
    status: 'loading' | 'success' | 'error';
    /** 詳細 (取得前・失敗時は null)。applyUpdate で反映した更新を含む。 */
    tenant: TenantDetail | null;
    /** 保持している ETag (取得前・失敗時は null)。 */
    etag: string | null;
    /** 取得の失敗 (status === 'error' のとき)。 */
    error: CpErrorInfo | null;
    /** 取り直す (取得中は status が loading になる)。412 などで requires_reload のときに使う。 */
    reload: () => void;
    /**
     * 更新操作の結果 (更新後のテナントと新しい ETag) を反映する。払い出し履歴は変えない。
     * 再実行のように履歴が増える操作の後は reload で取り直すこと。
     */
    applyUpdate: (update: TenantVersioned) => void;
};

/**
 * 詳細に更新後のテナントを重ねる関数
 * @param {TenantVersioned<TenantDetail>} base 取得した詳細
 * @param {TenantVersioned} update 更新後のテナントと ETag
 * @returns {TenantVersioned<TenantDetail>} 反映後の詳細
*/
export const mergeTenantUpdate = (base: TenantVersioned<TenantDetail>, update: TenantVersioned): TenantVersioned<TenantDetail> => {
    if (update.tenant.id !== base.tenant.id) return base;
    return { tenant: { ...base.tenant, ...update.tenant, provisioning_history: base.tenant.provisioning_history }, etag: update.etag };
};

/**
 * useVersionedResource 用に、本文と ETag の組で更新を重ねる関数
 * @param {WithEtag<TenantDetail>} current 現在の詳細
 * @param {TenantVersioned} update 更新後のテナントと ETag
 * @returns {WithEtag<TenantDetail>} 反映後の詳細
*/
const mergeTenantBody = (current: WithEtag<TenantDetail>, update: TenantVersioned): WithEtag<TenantDetail> => {
    const merged = mergeTenantUpdate({ tenant: current.body, etag: current.etag }, update);
    return { body: merged.tenant, etag: merged.etag };
};

/**
 * CP のテナント詳細を取得するカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * tenant_id が変わると取り直す。
 * @param {string} tenant_id テナント ID
 * @returns {TenantDetailState} 詳細の状態と操作
*/
export const useTenant = (tenant_id: string): TenantDetailState => {
    const client = useCpApiClient();
    const { status, value, etag, error, reload, applyUpdate } = useVersionedResource<TenantDetail, TenantVersioned>({
        key: `cp-tenant:${tenant_id}`,
        load: async () => {
            const { tenant, etag: loaded_etag } = await fetchTenant(client, tenant_id);
            return { body: tenant, etag: loaded_etag };
        },
        merge: mergeTenantBody,
        classify: classifyCpError,
    });
    return { status, tenant: value, etag, error, reload, applyUpdate };
};

export default useTenant;
