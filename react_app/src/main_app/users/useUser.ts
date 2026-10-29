/**
 * @description:
 * AP のユーザー詳細 (姓・名・ロールを含む) と ETag を取得・保持するカスタムフック
 * 保持している ETag は useUserActions の update の If-Match に渡す。
 * - 詳細の GET は姓・名・ロールを IdP から取り直す。写しと違えばサーバーが写しを更新するため、一覧の version より新しい
 *   version (と ETag) が返ることがある。If-Match には常にこのフックの etag (GET / 更新の応答の ETag) を使う。
 * - 更新 (PATCH) の応答は UserDetail (ロールを含む) のため、applyUpdate は取り直さずに応答をそのまま重ねる。
 *   ただし応答のロールが送ったロールと食い違う場合 (写しが IdP と食い違っていた) は roles_stale: true で通知され、取り直す。
*/
import { useCallback } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { UserDetail } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchUser } from '@/main_app/api/users';
import type { WithEtag } from '@/shared/api/etag';
import { useVersionedResource } from '@/shared/hooks/useVersionedResource';

/**
 * ユーザーの最新の状態とその ETag (作成・更新の結果)。
 */
export type UserVersioned = {
    /** 作成・更新後のユーザー (姓・名・ロールを含む。変更しない項目の姓・名・ロールは写しの値)。 */
    user: UserDetail;
    etag: string;
    /**
     * 応答のロールを信用せず、詳細を取り直す必要がある。
     * 更新の応答はロールを含むため通常は false。送ったロールと応答のロールが食い違う場合 (写しが IdP と食い違っていた) だけ true。
     */
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
    /** 取得の失敗 (status === 'error' のとき。404 user_not_found、IdP からの取得失敗は 502)。 */
    error: AppErrorInfo | null;
    /** 取り直す (取得中は status が loading になる)。412 などで requires_reload のときに使う。 */
    reload: () => void;
    /**
     * 更新操作の結果を反映する (useUserActions の onUpdated につなぐ)。別のユーザーへの更新は無視する。
     * 応答 (ロールを含む) をそのまま重ねる。roles_stale の更新だけは取り直す。
     */
    applyUpdate: (update: UserVersioned) => void;
};

/**
 * 詳細に更新後のユーザーを重ねる関数 (更新の応答は詳細と同じ項目を持つため、応答で置き換える)
 * @param {WithEtag<UserDetail>} current 現在の詳細
 * @param {UserVersioned} update 更新後のユーザーと ETag
 * @returns {WithEtag<UserDetail>} 反映後の詳細 (別のユーザーへの更新なら current)
*/
export const mergeUserUpdate = (current: WithEtag<UserDetail>, update: UserVersioned): WithEtag<UserDetail> => {
    if (update.user.id !== current.body.id) return current;
    return { body: { ...current.body, ...update.user }, etag: update.etag };
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
