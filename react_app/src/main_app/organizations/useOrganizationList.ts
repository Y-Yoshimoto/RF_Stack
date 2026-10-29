/**
 * @description:
 * AP の組織一覧 (論理削除済みを除く) を取得するカスタムフック (カーソル方式の「さらに読み込む」)
 * 並び順が変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる。
 * 一覧の要素にメンバーは含まれない (useOrganization で取得する)。各要素の version から ifMatchOf で If-Match を作れる。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { OrganizationListQuery, OrganizationRead } from '@/main_app/api/contract';
import { classifyAppError } from '@/main_app/api/errors';
import { buildOrganizationListUrl, fetchOrganizationPage, toOrganizationListQuery, type OrganizationListFilter } from '@/main_app/api/organizations';
import { useCursorList, type CursorListState } from '@/shared/hooks/useCursorList';

/**
 * 組織一覧の状態と操作 (total は AP の一覧では常に null)。
 * replaceItem / removeItem は useOrganizationActions の onUpdated で受け取った結果の反映に使う (作成は reload)。
 */
export type OrganizationListState = CursorListState<OrganizationRead>;

/**
 * AP の組織一覧を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {OrganizationListFilter} filter 並び順・件数
 * @returns {OrganizationListState} 一覧の状態と操作
*/
export const useOrganizationList = (filter: OrganizationListFilter = {}): OrganizationListState => {
    const client = useAppApiClient();
    const query: OrganizationListQuery = toOrganizationListQuery(filter);
    return useCursorList<OrganizationRead>({
        query_key: `app-organizations:${buildOrganizationListUrl(query)}`,
        fetchPage: (cursor) => fetchOrganizationPage(client, cursor === null ? query : { ...query, cursor }),
        classify: classifyAppError,
    });
};

export default useOrganizationList;
