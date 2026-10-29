/**
 * @description:
 * AP のユーザーの変更操作 (作成・更新) のカスタムフック
 *
 * - member など tenant_admin でないユーザーでは API を呼ばずに失敗 (kind: forbidden) にする (useAppPermissions)
 * - 自分自身の無効化・自分の tenant_admin の解除は API を呼ばずに失敗 (kind: conflict、code: user_self_modification_forbidden) にする。
 *   自分の ID は options.self_user_id (useMe の self_user_id) で受け取る。未取得 (null) の間は判定せず API に任せる (API も 409 で拒否する)
 * - 更新は保持している ETag を If-Match に付ける。412 / 428 は requires_reload のエラーになる (useUser の reload で取り直してやり直す)
 * - 更新の応答は UserDetail (姓・名・ロールを含む) のため、通常は onUpdated の user をそのまま反映すればよい (roles_stale: false)。
 *   ロールを送った更新で、応答のロールが送ったロール (+ 既定ロール) と食い違う場合だけ roles_stale: true で通知する
 *   (IdP 上で変化が無かったため写しが書き換わらず、写しが IdP と食い違っていた。useUser の applyUpdate が取り直す)。
 *   ロールを送らない更新の応答のロールは写しの値 (詳細の GET で IdP と揃えた時点の値)。GET の後に IdP 側で直接変更された場合は古い
 * - 一時パスワードは issued_credentials にだけ保持し、dismissCredentials・次の操作の開始・一定時間の経過・アンマウントで消す。
 *   操作の戻り値・onUpdated・エラーには含めない。ログにも出さない
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
*/
import { useCallback } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { UserCreate, UserCredentials } from '@/main_app/api/contract';
import { AppGuardError, classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { createUser, rolesMatchRequest, selfModificationOf, toUserUpdate, updateUser, type UserChanges, type UserTarget } from '@/main_app/api/users';
import { useAppPermissions } from '@/main_app/auth/useAppAuth';
import type { UserVersioned } from '@/main_app/users/useUser';
import { useActionRunner, type ActionOutcome } from '@/shared/hooks/useActionRunner';
import { DEFAULT_SECRET_TTL_MS, useEphemeralValue } from '@/shared/hooks/useEphemeralValue';

/** 一時パスワードを保持する既定の時間 (ミリ秒)。画面は表示を閉じたら dismissCredentials を呼ぶこと */
export const DEFAULT_CREDENTIALS_TTL_MS = DEFAULT_SECRET_TTL_MS;

/**
 * 変更操作の種類。
 */
export type UserActionName = 'create' | 'update';

/**
 * 変更操作の失敗。
 */
export type UserActionFailure = AppErrorInfo & {
    action: UserActionName;
    /** 対象のユーザー ID (作成では null)。 */
    user_id: string | null;
};

/**
 * 成功の通知 (一時パスワードは含まない)。
 */
export type UserActionUpdate = UserVersioned & { action: UserActionName };

/**
 * 変更操作の結果。
 */
export type UserActionResult = ({ ok: true } & UserActionUpdate) | { ok: false; failure: UserActionFailure };

/**
 * 作成で発行されたログイン情報。一度だけ表示する。
 */
export type IssuedUserCredentials = UserCredentials & {
    user_id: string;
    display_name: string;
};

export type UseUserActionsOptions = {
    /** 自分のユーザー ID (useMe の self_user_id)。自分自身への禁止操作を API を呼ばずに弾くために使う。未取得なら null。 */
    self_user_id: string | null;
    /** 成功時に呼ばれる (useUser の applyUpdate や一覧の replaceItem / reload につなぐ)。一時パスワードは渡さない。 */
    onUpdated?: (update: UserActionUpdate) => void;
    /** 一時パスワードを保持する時間 (ミリ秒)。 */
    credentials_ttl_ms?: number;
};

/**
 * 変更操作の状態と操作。
 */
export type UserActionsState = {
    /** 変更操作を使える (tenant_admin)。false のとき画面は変更操作の UI を表示しない。 */
    can_write: boolean;
    /** 実行中の操作 (無ければ null)。 */
    pending: UserActionName | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: UserActionFailure | null;
    /** 発行された一時パスワード (無ければ null)。 */
    issued_credentials: IssuedUserCredentials | null;
    /** 一時パスワードを破棄する (表示を閉じたときに呼ぶ)。 */
    dismissCredentials: () => void;
    clearFailure: () => void;
    /** ユーザーを作成する (201 で一時パスワードが issued_credentials に入る)。 */
    create: (input: UserCreate) => Promise<UserActionResult>;
    /** 姓名・ロール・有効/無効を更新する (指定した項目だけ。target.etag を If-Match に付ける)。 */
    update: (target: UserTarget, changes: UserChanges) => Promise<UserActionResult>;
};

const busyError = () => new AppGuardError('action_in_progress');
const toFailure = (info: AppErrorInfo, action: UserActionName, user_id: string | null): UserActionFailure => ({ ...info, action, user_id });

/**
 * 更新の前に弾く理由を返す関数 (変更なし・自分自身への禁止操作・ETag 未取得)
 * @param {UserTarget} target 対象と ETag
 * @param {UserChanges} changes 変更内容
 * @param {string | null} self_user_id 自分のユーザー ID
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
const updateGuardOf = (target: UserTarget, changes: UserChanges, self_user_id: string | null): AppGuardError | null => {
    if (Object.keys(toUserUpdate(changes)).length === 0) return new AppGuardError('empty_changes');
    const self_operation = selfModificationOf(target.user_id, self_user_id, changes);
    if (self_operation === 'deactivate') return new AppGuardError('self_deactivate');
    if (self_operation === 'remove_tenant_admin') return new AppGuardError('self_remove_tenant_admin');
    if (!target.etag) return new AppGuardError('missing_etag');
    return null;
};

/**
 * AP のユーザーの変更操作のカスタムフック (AppAuthProvider の内側で使う)
 * @param {UseUserActionsOptions} options 自分の ID・成功時の通知・一時パスワードの保持時間
 * @returns {UserActionsState} 状態と操作
*/
export const useUserActions = ({ self_user_id, onUpdated, credentials_ttl_ms = DEFAULT_CREDENTIALS_TTL_MS }: UseUserActionsOptions): UserActionsState => {
    const client = useAppApiClient();
    const { can_write } = useAppPermissions();
    const credentials = useEphemeralValue<IssuedUserCredentials>(credentials_ttl_ms);
    const { pending, failure, clearFailure, execute } = useActionRunner<UserActionName, UserActionFailure>({
        classify: classifyAppError,
        toFailure,
        busyError,
        // 次の操作を始めたら、前の一時パスワードは消す
        onStart: credentials.clear,
    });

    const finish = useCallback((outcome: ActionOutcome<UserActionUpdate, UserActionFailure>): UserActionResult => {
        if (!outcome.ok) return outcome;
        onUpdated?.(outcome.value);
        return { ok: true, ...outcome.value };
    }, [onUpdated]);

    const create = useCallback(async (input: UserCreate) => finish(await execute<UserActionUpdate>({
        action: 'create',
        target_id: null,
        precheck: () => (can_write ? null : new AppGuardError('write_not_allowed')),
        run: async () => {
            const { body, etag } = await createUser(client, input);
            credentials.set({ ...body.credentials, user_id: body.user.id, display_name: body.user.display_name });
            return { action: 'create', user: body.user, etag, roles_stale: false };
        },
    })), [execute, finish, client, can_write, credentials.set]);

    const update = useCallback(async (target: UserTarget, changes: UserChanges) => finish(await execute<UserActionUpdate>({
        action: 'update',
        target_id: target.user_id,
        precheck: () => (can_write ? updateGuardOf(target, changes, self_user_id) : new AppGuardError('write_not_allowed')),
        run: async () => {
            const update_body = toUserUpdate(changes);
            const { body, etag } = await updateUser(client, target.user_id, update_body, target.etag ?? '');
            return { action: 'update', user: body, etag, roles_stale: update_body.roles !== undefined && !rolesMatchRequest(update_body.roles, body.roles) };
        },
    })), [execute, finish, client, can_write, self_user_id]);

    return { can_write, pending, failure, issued_credentials: credentials.value, dismissCredentials: credentials.clear, clearFailure, create, update };
};

export default useUserActions;
