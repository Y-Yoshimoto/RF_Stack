/**
 * @description:
 * AP のユーザー一覧を取得するカスタムフック (カーソル方式の「さらに読み込む」)
 * 並び順・有効/無効・ID の絞り込みが変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる。
 * 一覧の要素の姓・名・ロールは AP の DB の写し (最後に同期した時点の値)。最新の値は useUser (詳細) で取得する。
 * 各要素の version から ifMatchOf で If-Match を作れる。
 * ID の絞り込み (filter.ids) は 1 回 100 件まで (超えると 422)。名前の解決には分割して取得する useUsersByIds を使う。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { UserListQuery, UserRead } from '@/main_app/api/contract';
import { classifyAppError } from '@/main_app/api/errors';
import { buildUserListUrl, fetchUserPage, toUserListQuery, type UserListFilter } from '@/main_app/api/users';
import { useCursorList, type CursorListState } from '@/shared/hooks/useCursorList';

/**
 * ユーザー一覧の状態と操作 (total は AP の一覧では常に null)。
 * replaceItem は useUserActions の onUpdated で受け取った更新後のユーザーの反映に使う。
 */
export type UserListState = CursorListState<UserRead>;

/**
 * AP のユーザー一覧を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {UserListFilter} filter 並び順・有効/無効・ID の絞り込み・件数
 * @returns {UserListState} 一覧の状態と操作
*/
export const useUserList = (filter: UserListFilter = {}): UserListState => {
    const client = useAppApiClient();
    const query: UserListQuery = toUserListQuery(filter);
    return useCursorList<UserRead>({
        query_key: `app-users:${buildUserListUrl(query)}`,
        fetchPage: (cursor) => fetchUserPage(client, cursor === null ? query : { ...query, cursor }),
        classify: classifyAppError,
    });
};

export default useUserList;
