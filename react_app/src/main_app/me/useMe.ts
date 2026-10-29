/**
 * @description:
 * ログイン中のテナントとユーザー (`/api/v1/me`) を取得するカスタムフック
 * プロフィール画面と、「自分」の判定 (useUserActions の self_user_id) に使う。
 * user.id は AP のユーザー ID で、ユーザー一覧の id・組織のメンバー ID と比較できる (認証基盤の sub ではない)。
 * 所属組織 (organizations) も同じ応答に含まれる (組織名順。論理削除済みを除く)。組織の一覧と詳細を全件取得して探す必要は無い。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { MeOrganization, MeRead } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchMe } from '@/main_app/api/me';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';

/**
 * プロフィールの状態と操作。
 */
export type MeState = {
    status: 'loading' | 'success' | 'error';
    /** テナントとユーザー (取得前・失敗時は null)。 */
    me: MeRead | null;
    /** 自分のユーザー ID (取得前・失敗時は null)。 */
    self_user_id: string | null;
    /** 所属する組織 (組織名順。取得前・失敗時・所属が無ければ空の配列)。me.organizations と同じ値。 */
    organizations: readonly MeOrganization[];
    /** 取得の失敗 (status === 'error' のとき。401 はログイン画面へ遷移するため画面での表示は不要)。 */
    error: AppErrorInfo | null;
    /** 取り直す。 */
    reload: () => void;
};

/**
 * 所属組織の取得状態 (プロフィール画面の所属組織の表示用。pages/Profile/useMyOrganizations の置き換え)。
 */
export type MyOrganizationsState = {
    status: 'loading' | 'success' | 'error';
    /** 所属している組織 (組織名順)。 */
    organizations: readonly MeOrganization[];
    error: AppErrorInfo | null;
    /** 取り直す (`/api/v1/me` を取り直す)。 */
    reload: () => void;
};

const NO_ORGANIZATIONS: readonly MeOrganization[] = [];

/**
 * useMe の結果から所属組織の取得状態を作る関数 (`/api/v1/me` を二重に取得しないよう、フックではなく関数にしている)
 * @param {MeState} me useMe の戻り値
 * @returns {MyOrganizationsState} 所属組織の取得状態
*/
export const myOrganizationsOf = (me: MeState): MyOrganizationsState => ({ status: me.status, organizations: me.organizations, error: me.error, reload: me.reload });

/**
 * ログイン中のテナントとユーザーを取得するカスタムフック (AppAuthProvider の内側で使う)
 * @returns {MeState} プロフィールの状態と操作
*/
export const useMe = (): MeState => {
    const client = useAppApiClient();
    const { result, reload } = useAsyncValue(() => fetchMe(client), 'app-me');
    if (result.status === 'loading') return { status: 'loading', me: null, self_user_id: null, organizations: NO_ORGANIZATIONS, error: null, reload };
    if (result.status === 'error') return { status: 'error', me: null, self_user_id: null, organizations: NO_ORGANIZATIONS, error: classifyAppError(result.error), reload };
    return { status: 'success', me: result.value, self_user_id: result.value.user.id, organizations: result.value.organizations, error: null, reload };
};

export default useMe;
