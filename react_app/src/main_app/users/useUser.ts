/**
 * @description:
 * AP のユーザー詳細 (ロールを含む) と ETag を取得・保持するカスタムフック
 * 保持している ETag は useUserActions の update の If-Match に渡す。
 * 更新 (PATCH) の応答にロールは含まれないため、ロールを変えた更新を applyUpdate で受け取ると取り直す。
*/
import { useCallback } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { UserDetail, UserRead } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchUser } from '@/main_app/api/users';
import type { WithEtag } from '@/shared/api/etag';
import { useVersionedResource } from '@/shared/hooks/useVersionedResource';

/**
 * ユーザーの最新の状態とその ETag (作成・更新の結果)。
 */
export type UserVersioned = {
    /** 更新後のユーザー (更新の応答はロールを含まない)。 */
    user: UserRead;
    etag: string;
    /** ロールを変えたため、詳細のロールを取り直す必要がある。 */
    roles_stale: boolean;
};

/**
 * ユーザー詳細の状態と操作。
 */
export type UserDetailState = {
    status: 'loading' | 'success' | 'error';
    /** 詳細 (取得前・失敗時は null)。applyUpdate で反映した更新を含む。 */
    user: UserDetail | null;
    /** 保持している ETag (取得前・失敗時は null)。 */
    etag: string | null;
    /** 取得の失敗 (status === 'error' のとき。404 user_not_found、ロールの取得失敗は 502)。 */
    error: AppErrorInfo | null;
    /** 取り直す (取得中は status が loading になる)。412 などで requires_reload のときに使う。 */
    reload: () => void;
    /**
     * 更新操作の結果を反映する (useUserActions の onUpdated につなぐ)。別のユーザーへの更新は無視する。
     * roles_stale の更新は取り直す (ロールは GET でしか分からないため)。
     */
    applyUpdate: (update: UserVersioned) => void;
};

/**
 * 詳細に更新後のユーザーを重ねる関数 (ロールは詳細のものを残す)
 * @param {WithEtag<UserDetail>} current 現在の詳細
 * @param {UserVersioned} update 更新後のユーザーと ETag
 * @returns {WithEtag<UserDetail>} 反映後の詳細
*/
export const mergeUserUpdate = (current: WithEtag<UserDetail>, update: UserVersioned): WithEtag<UserDetail> => {
    if (update.user.id !== current.body.id) return current;
    const { id, email, display_name, is_active, last_login_at, version, created_at, updated_at } = update.user;
    return { body: { ...current.body, id, email, display_name, is_active, last_login_at, version, created_at, updated_at }, etag: update.etag };
};

/**
 * AP のユーザー詳細を取得するカスタムフック (AppAuthProvider の内側で使う)
 * user_id が変わると取り直す。
 * @param {string} user_id ユーザー ID
 * @returns {UserDetailState} 詳細の状態と操作
*/
export const useUser = (user_id: string): UserDetailState => {
    const client = useAppApiClient();
    const { status, value, etag, error, reload, applyUpdate: overlay } = useVersionedResource<UserDetail, UserVersioned>({
        key: `app-user:${user_id}`,
        load: () => fetchUser(client, user_id),
        merge: mergeUserUpdate,
        classify: classifyAppError,
    });
    const applyUpdate = useCallback((update: UserVersioned) => {
        if (update.user.id !== user_id) return;
        if (update.roles_stale) reload();
        else overlay(update);
    }, [user_id, reload, overlay]);
    return { status, user: value, etag, error, reload, applyUpdate };
};

export default useUser;
