// AP の `/api/v1/me` を呼び出す関数
// フック (main_app/me/) から使う。ApiClient を引数で受け取り、副作用はそれだけにする (テストで差し替えられる)。
import type { ApiClient } from '@/shared/api/client';
import { requireBody } from '@/shared/api/etag';
import { APP_API_PATHS, type MeRead } from './contract';

/**
 * ログイン中のテナントとユーザーを取得する関数
 * @param {ApiClient} client API クライアント
 * @returns {Promise<MeRead>} テナントとユーザー (user.id は AP のユーザー ID)
*/
export const fetchMe = async (client: ApiClient): Promise<MeRead> => {
    return requireBody(await client.request<MeRead>({ url: APP_API_PATHS.ME, method: 'GET' }), APP_API_PATHS.ME);
};
