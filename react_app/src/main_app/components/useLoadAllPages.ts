/**
 * @description:
 * カーソル方式の一覧 (useUserList など) の全ページを、続けて取得するカスタムフック
 * 検索 API が無いため、選択肢 (候補) の一覧に使う (useTodoChoices)。件数が少ない前提 (1 テナントのユーザー・組織は数十件程度) で、全ページを順に取得する。
 * ID から名前を引く用途には使わない: ユーザーは useUsersByIds (`GET /api/v1/users?ids=`)、自分の所属組織は useMe の organizations を使う。
 * 取得の失敗 (load_more_error) で止まる。再開は一覧の loadMore / reload で行う。
*/
import { useEffect } from 'react';
import type { CursorListState } from '@/shared/hooks/useCursorList';

/**
 * 全ページの取得状況。
 */
export type LoadAllPagesState = {
    /** 全ページを取得し終えた。 */
    is_complete: boolean;
};

/**
 * 一覧の全ページを続けて取得するカスタムフック
 * @param {CursorListState<T>} list 一覧 (useUserList・useOrganizationList の戻り値)
 * @returns {LoadAllPagesState} 取得状況
*/
export const useLoadAllPages = <T,>(list: CursorListState<T>): LoadAllPagesState => {
    const { status, has_more, is_loading_more, load_more_error, loadMore } = list;
    useEffect(() => {
        if (status === 'success' && has_more && !is_loading_more && load_more_error === null) loadMore();
    }, [status, has_more, is_loading_more, load_more_error, loadMore]);
    return { is_complete: status === 'success' && !has_more };
};

export default useLoadAllPages;
