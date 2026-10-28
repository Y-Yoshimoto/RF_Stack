/**
 * @description:
 * テナントの全ユーザーを取得するカスタムフック (組織のメンバーの名前の表示・選択に使う)
 * 組織のメンバーはユーザー ID でしか分からず、ID 指定でユーザーを絞り込む API は無い。そのためユーザー一覧 (useUserList) の全ページを取得して名前を引く。
 * 1 テナントのユーザーが数十人程度という前提の実装で、ページ単位 (limit 200) で続けて取得する。ユーザー数が増える場合は、API 側に ID 指定の取得を用意して置き換えること。
 * 画面側の合成だけのフック。react-domain が管理するフックに移す場合はこのファイルごと移動する。
*/
import type { UserRead } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { useLoadAllPages } from '@/main_app/components/useLoadAllPages';
import { useUserList } from '@/main_app/users/useUserList';

/** 1 回の取得の件数 (API の上限) */
const PAGE_LIMIT = 200;

/**
 * 全ユーザーの取得状態。
 */
export type AllUsersState = {
    /** 全ページの取得が終わるまでは loading。 */
    status: 'loading' | 'success' | 'error';
    /** 取得済みのユーザー (有効・無効の両方)。 */
    users: UserRead[];
    /** 取得の失敗 (先頭ページ、または続きのページ)。 */
    error: AppErrorInfo | null;
    /** 先頭から取り直す。 */
    reload: () => void;
};

/**
 * テナントの全ユーザーを取得するカスタムフック (AppAuthProvider の内側で使う)
 * @returns {AllUsersState} 取得状態
*/
export const useAllUsers = (): AllUsersState => {
    const list = useUserList({ limit: PAGE_LIMIT });
    const { is_complete } = useLoadAllPages(list);
    const error = list.error ?? list.load_more_error;
    if (error !== null) return { status: 'error', users: list.items, error, reload: list.reload };
    if (!is_complete) return { status: 'loading', users: list.items, error: null, reload: list.reload };
    return { status: 'success', users: list.items, error: null, reload: list.reload };
};

export default useAllUsers;
