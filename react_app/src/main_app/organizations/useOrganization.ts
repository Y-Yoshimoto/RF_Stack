/**
 * @description:
 * AP の組織の詳細 (メンバーのユーザー ID を含む) と ETag を取得・保持するカスタムフック
 * 保持している ETag は useOrganizationActions の update / remove / setMembers の If-Match に渡す。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { OrganizationDetail, OrganizationRead } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchOrganization } from '@/main_app/api/organizations';
import type { WithEtag } from '@/shared/api/etag';
import { useVersionedResource } from '@/shared/hooks/useVersionedResource';

/**
 * 組織の変更操作の結果 (useOrganizationActions の onUpdated で通知される)。
 * - create / set_members: メンバーを含む組織
 * - update: メンバーを含まない組織 (組織名の変更)
 * - delete: 削除した組織の ID (以降この組織の API は 404)
 */
export type OrganizationActionUpdate =
    | { action: 'create' | 'set_members'; organization: OrganizationDetail; etag: string }
    | { action: 'update'; organization: OrganizationRead; etag: string }
    | { action: 'delete'; organization_id: string };

/**
 * 組織の詳細の状態と操作。
 */
export type OrganizationDetailState = {
    status: 'loading' | 'success' | 'error';
    /** 詳細 (取得前・失敗時は null)。applyUpdate で反映した更新を含む。 */
    organization: OrganizationDetail | null;
    /** 保持している ETag (取得前・失敗時は null)。 */
    etag: string | null;
    /** 取得の失敗 (status === 'error' のとき。削除済み・他テナント・存在しない組織は 404 organization_not_found)。 */
    error: AppErrorInfo | null;
    /** 取り直す (取得中は status が loading になる)。412 などで requires_reload のときに使う。 */
    reload: () => void;
    /** 更新操作の結果を反映する (useOrganizationActions の onUpdated につなぐ)。別の組織への更新・削除は無視する (削除後は画面を離れること)。 */
    applyUpdate: (update: OrganizationActionUpdate) => void;
};

/**
 * 詳細に更新後の組織を重ねる関数 (メンバーを含まない更新ではメンバーを残す)
 * @param {WithEtag<OrganizationDetail>} current 現在の詳細
 * @param {OrganizationActionUpdate} update 更新操作の結果
 * @returns {WithEtag<OrganizationDetail>} 反映後の詳細
*/
export const mergeOrganizationUpdate = (current: WithEtag<OrganizationDetail>, update: OrganizationActionUpdate): WithEtag<OrganizationDetail> => {
    if (update.action === 'delete' || update.organization.id !== current.body.id) return current;
    if (update.action === 'update') {
        const { id, name, version, created_at, updated_at } = update.organization;
        return { body: { ...current.body, id, name, version, created_at, updated_at }, etag: update.etag };
    }
    return { body: update.organization, etag: update.etag };
};

/**
 * AP の組織の詳細を取得するカスタムフック (AppAuthProvider の内側で使う)
 * organization_id が変わると取り直す。
 * @param {string} organization_id 組織 ID
 * @returns {OrganizationDetailState} 詳細の状態と操作
*/
export const useOrganization = (organization_id: string): OrganizationDetailState => {
    const client = useAppApiClient();
    const { status, value, etag, error, reload, applyUpdate } = useVersionedResource<OrganizationDetail, OrganizationActionUpdate>({
        key: `app-organization:${organization_id}`,
        load: () => fetchOrganization(client, organization_id),
        merge: mergeOrganizationUpdate,
        classify: classifyAppError,
    });
    return { status, organization: value, etag, error, reload, applyUpdate };
};

export default useOrganization;
