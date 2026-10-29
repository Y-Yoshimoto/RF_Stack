/**
 * @description:
 * AP の組織の変更操作 (作成・組織名の変更・削除・メンバーの置き換え) のカスタムフック
 *
 * - member など tenant_admin でないユーザーでは API を呼ばずに失敗 (kind: forbidden) にする (useAppPermissions)
 * - 変更・削除・メンバーの置き換えは保持している ETag を If-Match に付ける。ETag が無ければ API を呼ばずに失敗
 *   (kind: precondition_required)。412 / 428 は requires_reload のエラーになる (useOrganization の reload で取り直してやり直す)
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
*/
import { useCallback } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { OrganizationCreate, OrganizationUpdate } from '@/main_app/api/contract';
import { AppGuardError, classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { createOrganization, deleteOrganization, replaceOrganizationMembers, updateOrganization, type OrganizationTarget } from '@/main_app/api/organizations';
import { useAppPermissions } from '@/main_app/auth/useAppAuth';
import type { OrganizationActionUpdate } from '@/main_app/organizations/useOrganization';
import { useActionRunner, type ActionOutcome } from '@/shared/hooks/useActionRunner';

/**
 * 変更操作の種類。
 */
export type OrganizationActionName = OrganizationActionUpdate['action'];

/**
 * 変更操作の失敗。
 */
export type OrganizationActionFailure = AppErrorInfo & {
    action: OrganizationActionName;
    /** 対象の組織 ID (作成では null)。 */
    organization_id: string | null;
};

/**
 * 変更操作の結果。
 */
export type OrganizationActionResult = ({ ok: true } & OrganizationActionUpdate) | { ok: false; failure: OrganizationActionFailure };

export type UseOrganizationActionsOptions = {
    /** 成功時に呼ばれる (useOrganization の applyUpdate や一覧の replaceItem / removeItem / reload につなぐ)。 */
    onUpdated?: (update: OrganizationActionUpdate) => void;
};

/**
 * 変更操作の状態と操作。
 */
export type OrganizationActionsState = {
    /** 変更操作を使える (tenant_admin)。false のとき画面は変更操作の UI を表示しない。 */
    can_write: boolean;
    /** 実行中の操作 (無ければ null)。 */
    pending: OrganizationActionName | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: OrganizationActionFailure | null;
    clearFailure: () => void;
    /** 組織を作成する (メンバーは空。重複は 409 organization_name_already_exists)。 */
    create: (input: OrganizationCreate) => Promise<OrganizationActionResult>;
    /** 組織名を変更する (target.etag を If-Match に付ける)。 */
    update: (target: OrganizationTarget, input: OrganizationUpdate) => Promise<OrganizationActionResult>;
    /** 組織を削除する (論理削除。target.etag を If-Match に付ける)。 */
    remove: (target: OrganizationTarget) => Promise<OrganizationActionResult>;
    /** メンバーを user_ids に置き換える (全置換。target.etag を If-Match に付ける。存在しないユーザーは 422 invalid_organization_members)。 */
    setMembers: (target: OrganizationTarget, user_ids: readonly string[]) => Promise<OrganizationActionResult>;
};

const busyError = () => new AppGuardError('action_in_progress');
const toFailure = (info: AppErrorInfo, action: OrganizationActionName, organization_id: string | null): OrganizationActionFailure => ({ ...info, action, organization_id });

/**
 * AP の組織の変更操作のカスタムフック (AppAuthProvider の内側で使う)
 * @param {UseOrganizationActionsOptions} options 成功時の通知
 * @returns {OrganizationActionsState} 状態と操作
*/
export const useOrganizationActions = ({ onUpdated }: UseOrganizationActionsOptions = {}): OrganizationActionsState => {
    const client = useAppApiClient();
    const { can_write } = useAppPermissions();
    const { pending, failure, clearFailure, execute } = useActionRunner<OrganizationActionName, OrganizationActionFailure>({ classify: classifyAppError, toFailure, busyError });

    const finish = useCallback((outcome: ActionOutcome<OrganizationActionUpdate, OrganizationActionFailure>): OrganizationActionResult => {
        if (!outcome.ok) return outcome;
        onUpdated?.(outcome.value);
        return { ok: true, ...outcome.value };
    }, [onUpdated]);

    /**
     * 権限と ETag を確かめる関数を作る関数
     * @param {string | null | undefined} etag If-Match に付ける ETag (作成では undefined で確かめない)
     * @returns {() => AppGuardError | null} 確認関数
    */
    const guardOf = useCallback((etag?: string | null) => (): AppGuardError | null => {
        if (!can_write) return new AppGuardError('write_not_allowed');
        if (etag !== undefined && !etag) return new AppGuardError('missing_etag');
        return null;
    }, [can_write]);

    const create = useCallback(async (input: OrganizationCreate) => finish(await execute<OrganizationActionUpdate>({
        action: 'create',
        target_id: null,
        precheck: guardOf(),
        run: async () => {
            const { body, etag } = await createOrganization(client, input);
            return { action: 'create', organization: body, etag };
        },
    })), [execute, finish, guardOf, client]);

    const update = useCallback(async (target: OrganizationTarget, input: OrganizationUpdate) => finish(await execute<OrganizationActionUpdate>({
        action: 'update',
        target_id: target.organization_id,
        precheck: guardOf(target.etag),
        run: async () => {
            const { body, etag } = await updateOrganization(client, target.organization_id, input, target.etag ?? '');
            return { action: 'update', organization: body, etag };
        },
    })), [execute, finish, guardOf, client]);

    const remove = useCallback(async (target: OrganizationTarget) => finish(await execute<OrganizationActionUpdate>({
        action: 'delete',
        target_id: target.organization_id,
        precheck: guardOf(target.etag),
        run: async () => {
            await deleteOrganization(client, target.organization_id, target.etag ?? '');
            return { action: 'delete', organization_id: target.organization_id };
        },
    })), [execute, finish, guardOf, client]);

    const setMembers = useCallback(async (target: OrganizationTarget, user_ids: readonly string[]) => finish(await execute<OrganizationActionUpdate>({
        action: 'set_members',
        target_id: target.organization_id,
        precheck: guardOf(target.etag),
        run: async () => {
            const { body, etag } = await replaceOrganizationMembers(client, target.organization_id, user_ids, target.etag ?? '');
            return { action: 'set_members', organization: body, etag };
        },
    })), [execute, finish, guardOf, client]);

    return { can_write, pending, failure, clearFailure, create, update, remove, setMembers };
};

export default useOrganizationActions;
