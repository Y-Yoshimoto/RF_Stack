/**
 * @description:
 * ユーザー ID からユーザー (表示名・有効/無効・メール等) を引くカスタムフック (組織のメンバー・ID しか分からないユーザーの名前の解決用)
 * `GET /api/v1/users?ids=...` を 100 件ずつに分けて取得する (fetchUsersByIds)。テナントの全ユーザーを取得する必要は無い。
 * - ID の集合 (順序・重複は問わない) が変わるか reload を呼ぶと取り直す。古い取得の結果は捨てる。取得中は users が空になる
 * - 存在しない ID・他テナントの ID・UUID でない ID は users に含まれず missing_ids に入る (画面では「不明なユーザー」と表示する)
 * - 1 回でも取得に失敗すれば error (一部だけの結果は返さない)
 * - ID が空なら API を呼ばずに success
 * 姓・名・ロールは AP の DB の写し (最後に同期した時点の値)。
*/
import { useMemo } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { UserRead } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchUsersByIds, uniqueUserIdsOf } from '@/main_app/api/users';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';

/**
 * ID 指定のユーザーの取得状態。
 */
export type UsersByIdsState = {
    status: 'loading' | 'success' | 'error';
    /** 見つかったユーザー (キーはユーザー ID。取得前・失敗時は空)。 */
    users: ReadonlyMap<string, UserRead>;
    /** 見つかったユーザーを、指定した ID の順に並べたもの (重複を除く。見つからなかった ID は含まない)。 */
    items: readonly UserRead[];
    /** 指定したが見つからなかった ID (指定した順。success のときだけ入る)。 */
    missing_ids: readonly string[];
    /** 取得の失敗 (status === 'error' のとき)。 */
    error: AppErrorInfo | null;
    /** 取り直す。 */
    reload: () => void;
    /**
     * ID からユーザーを引く (見つからない・取得前なら null)。
     * @param {string} user_id ユーザー ID
     * @returns {UserRead | null} ユーザー
     */
    userOf: (user_id: string) => UserRead | null;
};

const NO_USERS: ReadonlyMap<string, UserRead> = new Map();
const NO_IDS: readonly string[] = [];
const NO_ITEMS: readonly UserRead[] = [];

/**
 * ユーザーの配列を ID で引ける Map にする関数
 * @param {readonly UserRead[]} users ユーザー
 * @returns {Map<string, UserRead>} ID → ユーザー
*/
export const usersByIdOf = (users: readonly UserRead[]): Map<string, UserRead> => new Map(users.map((user) => [user.id, user]));

/**
 * 指定した ID の順に、見つかったユーザーと見つからなかった ID を分ける関数
 * @param {readonly string[]} user_ids 指定した ID (重複を除いたもの)
 * @param {ReadonlyMap<string, UserRead>} users 見つかったユーザー
 * @returns {{ items: UserRead[]; missing_ids: string[] }} 見つかったユーザーと見つからなかった ID
*/
export const resolveUserIds = (user_ids: readonly string[], users: ReadonlyMap<string, UserRead>): { items: UserRead[]; missing_ids: string[] } => {
    const items: UserRead[] = [];
    const missing_ids: string[] = [];
    for (const id of user_ids) {
        const user = users.get(id);
        if (user) items.push(user);
        else missing_ids.push(id);
    }
    return { items, missing_ids };
};

/**
 * ID を指定してユーザーを取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {readonly string[]} user_ids ユーザー ID (重複・順序は問わない。毎回新しい配列を渡しても、集合が同じなら取り直さない)
 * @returns {UsersByIdsState} 取得状態
*/
export const useUsersByIds = (user_ids: readonly string[]): UsersByIdsState => {
    const client = useAppApiClient();
    // 表示順は指定した順、取得のキーは集合 (並べ替えたもの) にする
    const ordered_key = JSON.stringify(uniqueUserIdsOf(user_ids));
    const ordered_ids = useMemo((): readonly string[] => JSON.parse(ordered_key) as string[], [ordered_key]);
    const set_key = JSON.stringify([...ordered_ids].sort());
    const { result, reload } = useAsyncValue(
        async () => (ordered_ids.length === 0 ? NO_USERS : usersByIdOf(await fetchUsersByIds(client, ordered_ids))),
        `app-users-by-ids:${set_key}`,
    );
    const users = result.status === 'success' ? result.value : NO_USERS;
    const resolved = useMemo(() => resolveUserIds(ordered_ids, users), [ordered_ids, users]);
    const userOf = useMemo(() => (user_id: string): UserRead | null => users.get(user_id) ?? null, [users]);

    if (result.status === 'loading') return { status: 'loading', users: NO_USERS, items: NO_ITEMS, missing_ids: NO_IDS, error: null, reload, userOf };
    if (result.status === 'error') return { status: 'error', users: NO_USERS, items: NO_ITEMS, missing_ids: NO_IDS, error: classifyAppError(result.error), reload, userOf };
    return { status: 'success', users, items: resolved.items, missing_ids: resolved.missing_ids, error: null, reload, userOf };
};

export default useUsersByIds;
