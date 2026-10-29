// ToDo のアクティビティが参照するユーザーの名前を解決する関数 (純粋関数)
// `GET /api/v1/todos/{todo_id}/activities` の応答はページごとに users (ユーザー ID → 表示名・有効/無効) を持つ。
// 対象は操作者 (actor_id) と payload のユーザー ID (created の values.assignee_ids、assignees_changed の added / removed)。
// checklist_changed の payload はユーザー ID を持たない (完了した人は操作者)。参照するのは操作者だけ。
// キーが無い ID (テナント内に存在しないユーザー) は「不明なユーザー」として扱う (user: null)。
// payload の読み取りは activity_payload.ts。
import type { TodoActivityRead, TodoActivityUser, TodoActivityUsers } from '@/main_app/api/contract';
import { todoActivityCreatedValuesOf, todoActivityIdDeltaOf } from './activity_payload';

/** 名前を引けないユーザーの既定の表示 (画面で別の文言にする場合は引数で渡す)。 */
export const UNKNOWN_USER_LABEL = '不明なユーザー';

/**
 * 取得したページの users を持つアクティビティ (useTodoActivities の items の要素)。
 * page_users は同じページの要素で同じオブジェクトを共有する (API の項目ではない)。
 */
export type TodoActivityEntry = TodoActivityRead & {
    /** このアクティビティを含むページの users。 */
    page_users: TodoActivityUsers;
};

/**
 * 名前を解決したユーザーの参照。
 */
export type TodoActivityUserRef = {
    user_id: string;
    /** 表示用の情報 (引けなければ null。画面では「不明なユーザー」と表示する)。 */
    user: TodoActivityUser | null;
};

/**
 * 担当者の追加と削除 (名前を解決したもの)。
 */
export type TodoActivityUserDelta = {
    added: TodoActivityUserRef[];
    removed: TodoActivityUserRef[];
};

const NO_USERS: TodoActivityUsers = {};

/**
 * ページの要素に、そのページの users を付ける関数
 * @param {readonly TodoActivityRead[]} items ページの要素
 * @param {TodoActivityUsers | undefined} users ページの users (古いモック等で無い場合は空として扱う)
 * @returns {TodoActivityEntry[]} users を付けた要素
*/
export const withPageUsers = (items: readonly TodoActivityRead[], users: TodoActivityUsers | undefined): TodoActivityEntry[] => {
    const page_users = users ?? NO_USERS;
    return items.map((item) => ({ ...item, page_users }));
};

/**
 * 読み込み済みの要素のページの users を 1 つにまとめる関数 (同じ ID は先に読み込んだページのものを残す)
 * @param {readonly { page_users: TodoActivityUsers }[]} items 読み込み済みの要素
 * @returns {TodoActivityUsers} ユーザー ID → 表示用の情報
*/
export const mergeTodoActivityUsers = (items: readonly { page_users: TodoActivityUsers }[]): TodoActivityUsers => {
    const merged: TodoActivityUsers = {};
    for (const page_users of new Set(items.map((item) => item.page_users))) {
        for (const [id, user] of Object.entries(page_users)) {
            if (!(id in merged)) merged[id] = user;
        }
    }
    return merged;
};

/**
 * ユーザー ID から表示用の情報を引く関数
 * @param {TodoActivityUsers} users ユーザー ID → 表示用の情報
 * @param {string} user_id ユーザー ID
 * @returns {TodoActivityUser | null} 表示用の情報 (引けなければ null)
*/
export const todoActivityUserOf = (users: TodoActivityUsers, user_id: string): TodoActivityUser | null => (Object.hasOwn(users, user_id) ? users[user_id] : null);

/**
 * ユーザー ID を名前を解決した参照にする関数
 * @param {TodoActivityUsers} users ユーザー ID → 表示用の情報
 * @param {readonly string[]} user_ids ユーザー ID
 * @returns {TodoActivityUserRef[]} 参照 (同じ順)
*/
export const todoActivityUserRefsOf = (users: TodoActivityUsers, user_ids: readonly string[]): TodoActivityUserRef[] => user_ids.map((user_id) => ({ user_id, user: todoActivityUserOf(users, user_id) }));

/**
 * ユーザー ID から表示名を引く関数を作る関数 (画面の NameLookup と同じ形)
 * @param {TodoActivityUsers} users ユーザー ID → 表示用の情報
 * @param {string} unknown_label 引けない場合の表示
 * @returns {(user_id: string) => string} 表示名を引く関数
*/
export const todoActivityUserNameLookupOf = (users: TodoActivityUsers, unknown_label: string = UNKNOWN_USER_LABEL) => (user_id: string): string => todoActivityUserOf(users, user_id)?.display_name ?? unknown_label;

/**
 * 操作者の名前を解決する関数 (users に無ければ actor_display_name を使う。有効/無効は users にある場合だけ分かる)
 * @param {TodoActivityRead} activity アクティビティ
 * @param {TodoActivityUsers} users ユーザー ID → 表示用の情報
 * @returns {TodoActivityUserRef} 操作者 (どちらにも無ければ user: null)
*/
export const todoActivityActorOf = (activity: TodoActivityRead, users: TodoActivityUsers): TodoActivityUserRef => {
    const user = todoActivityUserOf(users, activity.actor_id);
    if (user !== null) return { user_id: activity.actor_id, user };
    // users に無く表示名だけ分かる場合、有効/無効は分からないため有効として扱う
    return { user_id: activity.actor_id, user: activity.actor_display_name === null ? null : { display_name: activity.actor_display_name, is_active: true } };
};

/**
 * 担当者の追加と削除を、名前を解決して取り出す関数 (assignees_changed)
 * @param {TodoActivityRead} activity アクティビティ
 * @param {TodoActivityUsers} users ユーザー ID → 表示用の情報
 * @returns {TodoActivityUserDelta} 追加と削除 (assignees_changed 以外は空)
*/
export const todoActivityAssigneeDeltaOf = (activity: TodoActivityRead, users: TodoActivityUsers): TodoActivityUserDelta => {
    if (activity.action !== 'assignees_changed') return { added: [], removed: [] };
    const delta = todoActivityIdDeltaOf(activity);
    return { added: todoActivityUserRefsOf(users, delta.added), removed: todoActivityUserRefsOf(users, delta.removed) };
};

/**
 * 作成時の担当者を、名前を解決して取り出す関数 (created の values.assignee_ids)
 * @param {TodoActivityRead} activity アクティビティ
 * @param {TodoActivityUsers} users ユーザー ID → 表示用の情報
 * @returns {TodoActivityUserRef[]} 担当者 (created 以外・形が合わなければ空)
*/
export const todoActivityCreatedAssigneesOf = (activity: TodoActivityRead, users: TodoActivityUsers): TodoActivityUserRef[] => {
    const assignee_ids = todoActivityCreatedValuesOf(activity)?.assignee_ids;
    if (!Array.isArray(assignee_ids)) return [];
    return todoActivityUserRefsOf(users, assignee_ids.filter((id): id is string => typeof id === 'string'));
};
