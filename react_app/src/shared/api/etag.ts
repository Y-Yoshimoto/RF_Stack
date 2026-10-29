// 楽観ロック (ETag / If-Match) の共通部品 (03 §5.2、FastAPI: modules/api_common/etag.py)
// - GET と更新系の応答は `ETag: "<version>"` を返す。PATCH / PUT / DELETE は `If-Match` に同じ値を付ける
//   (無ければ 428 precondition_required、不一致は 412、形式不正は 400 invalid_if_match)。
// - プロキシ等で ETag ヘッダーが読めない場合は、本文の version から同じ値を作る。
// プレーン固有のエンドポイント関数 (control_plane_app/api、main_app/api) から使う。
import type { ApiClient } from '@/shared/api/client';
import type { ResourceObj } from '@/utils/libs/FetchComponents/type';

/**
 * 本文と ETag の組。ETag は楽観ロック (If-Match) にそのまま渡す値 (`"<version>"`)。
 */
export type WithEtag<T> = {
    body: T;
    etag: string;
};

/**
 * If-Match ヘッダーの値を作る関数
 * @param {number} version リソースの version (ETag と同じ値)
 * @returns {string} `"<version>"` 形式の値
*/
export const ifMatchOf = (version: number): string => `"${version}"`;

/**
 * If-Match ヘッダーを作る関数 (ETag が無い場合は付けない)
 * @param {string | null | undefined} etag ETag
 * @returns {Record<string, string>} ヘッダー
*/
export const ifMatchHeaders = (etag: string | null | undefined): Record<string, string> => (etag ? { 'If-Match': etag } : {});

/**
 * 本文と ETag ヘッダーを読み取る関数 (requestFetch の takeData に渡す)
 * ETag ヘッダーが読めない場合は空文字にし、呼び出し側で version から補う。
 * @param {Response} res レスポンス
 * @returns {Promise<WithEtag<T>>} 本文と ETag
*/
export const takeBodyWithEtag = async <T,>(res: Response): Promise<WithEtag<T>> => {
    const body = (await res.json()) as T;
    return { body, etag: res.headers.get('ETag') ?? '' };
};

/**
 * 応答が空でないことを確かめる関数
 * @param {T | null | undefined} value 応答
 * @param {string} url リクエストの URL (エラーメッセージ用)
 * @returns {T} 応答
*/
export const requireBody = <T,>(value: T | null | undefined, url: string): T => {
    if (value === null || value === undefined) throw new Error(`API の応答が空です: ${url}`);
    return value;
};

/**
 * ETag 付きのリクエストを送る関数
 * ETag ヘッダーが無い場合 (プロキシで落ちた等) は version から作る (値は同じ)。
 * @param {ApiClient} client API クライアント
 * @param {Omit<ResourceObj<WithEtag<T>>, 'takeData'>} resource_obj リクエスト (takeData は上書きする)
 * @param {(body: T) => number} versionOf 本文から version を取り出す関数
 * @returns {Promise<WithEtag<T>>} 本文と ETag
*/
export const requestWithEtag = async <T,>(client: ApiClient, resource_obj: Omit<ResourceObj<WithEtag<T>>, 'takeData'>, versionOf: (body: T) => number): Promise<WithEtag<T>> => {
    const value = requireBody(await client.request<WithEtag<T>>({ ...resource_obj, takeData: takeBodyWithEtag }), resource_obj.url);
    return { body: value.body, etag: value.etag !== '' ? value.etag : ifMatchOf(versionOf(value.body)) };
};
