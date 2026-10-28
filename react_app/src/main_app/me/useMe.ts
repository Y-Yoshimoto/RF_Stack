/**
 * @description:
 * ログイン中のテナントとユーザー (`/api/v1/me`) を取得するカスタムフック
 * プロフィール画面と、「自分」の判定 (useUserActions の self_user_id) に使う。
 * user.id は AP のユーザー ID で、ユーザー一覧の id・組織のメンバー ID と比較できる (認証基盤の sub ではない)。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { MeRead } from '@/main_app/api/contract';
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
    /** 取得の失敗 (status === 'error' のとき。401 はログイン画面へ遷移するため画面での表示は不要)。 */
    error: AppErrorInfo | null;
    /** 取り直す。 */
    reload: () => void;
};

/**
 * ログイン中のテナントとユーザーを取得するカスタムフック (AppAuthProvider の内側で使う)
 * @returns {MeState} プロフィールの状態と操作
*/
export const useMe = (): MeState => {
    const client = useAppApiClient();
    const { result, reload } = useAsyncValue(() => fetchMe(client), 'app-me');
    if (result.status === 'loading') return { status: 'loading', me: null, self_user_id: null, error: null, reload };
    if (result.status === 'error') return { status: 'error', me: null, self_user_id: null, error: classifyAppError(result.error), reload };
    return { status: 'success', me: result.value, self_user_id: result.value.user.id, error: null, reload };
};

export default useMe;
