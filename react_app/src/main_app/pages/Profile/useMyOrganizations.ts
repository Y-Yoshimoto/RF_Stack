/**
 * @description:
 * ログイン中のユーザーが所属する組織を取得するカスタムフック (プロフィール画面用)
 * 組織の一覧 API にメンバーは含まれず、ユーザーの所属組織を直接引く API も無い。そのため組織の一覧を全件取得し、各組織の詳細 (member_ids) を取得して自分が含まれるものを選ぶ。
 * 1 テナントの組織が数十件程度という前提の実装 (組織数 + 1 回のリクエスト)。件数が増える場合は、API 側に所属組織の取得を用意して置き換えること。
 * 画面側の合成だけのフック。react-domain が管理するフックに移す場合はこのファイルごと移動する。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { OrganizationRead } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchOrganization } from '@/main_app/api/organizations';
import { useLoadAllPages } from '@/main_app/components/useLoadAllPages';
import { useOrganizationList } from '@/main_app/organizations/useOrganizationList';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';

/** 1 回の取得の件数 (API の上限) */
const PAGE_LIMIT = 200;

/**
 * 所属組織の取得状態。
 */
export type MyOrganizationsState = {
    status: 'loading' | 'success' | 'error';
    /** 所属している組織 (組織名順)。 */
    organizations: OrganizationRead[];
    error: AppErrorInfo | null;
    /** 取り直す。 */
    reload: () => void;
};

/**
 * 自分が所属する組織を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {string} self_user_id 自分のユーザー ID (useMe の self_user_id)
 * @returns {MyOrganizationsState} 取得状態
*/
export const useMyOrganizations = (self_user_id: string): MyOrganizationsState => {
    const client = useAppApiClient();
    const list = useOrganizationList({ limit: PAGE_LIMIT });
    const { is_complete } = useLoadAllPages(list);
    const ids = list.items.map((item) => item.id).join(',');
    const { result, reload: reloadDetails } = useAsyncValue(
        async (): Promise<string[]> => {
            if (!is_complete) return [];
            const details = await Promise.all(list.items.map((item) => fetchOrganization(client, item.id)));
            return details.filter(({ body }) => body.member_ids.includes(self_user_id)).map(({ body }) => body.id);
        },
        `my-organizations:${self_user_id}:${is_complete}:${ids}`,
    );
    const reload = () => {
        list.reload();
        reloadDetails();
    };

    const list_error = list.error ?? list.load_more_error;
    if (list_error !== null) return { status: 'error', organizations: [], error: list_error, reload };
    if (!is_complete || result.status === 'loading') return { status: 'loading', organizations: [], error: null, reload };
    if (result.status === 'error') return { status: 'error', organizations: [], error: classifyAppError(result.error), reload };
    const member_of = new Set(result.value);
    return { status: 'success', organizations: list.items.filter((item) => member_of.has(item.id)), error: null, reload };
};

export default useMyOrganizations;
