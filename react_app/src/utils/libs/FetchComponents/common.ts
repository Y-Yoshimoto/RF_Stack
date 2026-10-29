// 共通関数群定義ファイル
//// 共通型定義読み込み
import { ResourceObj } from './type';
//// エラーレスポンス (Problem Details) の変換
import { toApiError } from './problem';
//// CSRF 対策ヘッダーの定数
import { CSRF_HEADER } from '@/constants.ts';

//// CSRF 対策ヘッダーを付与しない (参照系の) メソッド
const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS'];

/**
 * メソッドに応じた CSRF 対策ヘッダーを返す関数
 * 変更系メソッドには X-Requested-With: rf-stack を付与する (FastAPI 側で検証される)。
 * @param {string} method HTTP メソッド
 * @returns {Record<string, string>} 付与するヘッダー
*/
export const csrfHeadersFor = (method: string): Record<string, string> => {
    return SAFE_METHODS.includes(method.toUpperCase()) ? {} : { [CSRF_HEADER.NAME]: CSRF_HEADER.VALUE };
};

// Fetch API共通関数群
//// レスポンスからjsonデータを抽出する関数
export const takeDataDef = (r: Response) => r.json();
/**
 * リクエストオブジェクト生成関数
 * 変更系メソッドには CSRF 対策ヘッダー (X-Requested-With: rf-stack) を自動で付与する。
 * https://developer.mozilla.org/ja/docs/Web/API/Request
 * @param {ResourceObj<T>} param0 リクエスト情報
 * @returns {request: Request} リクエストオブジェクト
*/
export const generateRequestObject = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>) => {
    return new Request(url, {
        method: method,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...csrfHeadersFor(method), ...headers },
        body: (body === undefined) ? undefined : JSON.stringify(body),
    });
};

/**
 * リクエストを識別するキー文字列を生成する関数
 * @param {ResourceObj<T>} param0 リクエスト情報
 * @returns {string} 一意のキー文字列
*/
export const generateRequestKey = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>): string => {
    return `${url}-${method}-${JSON.stringify(body)}-${JSON.stringify(headers)}`;
}

/**
 * requestFetch リクエスト情報を受け取り、Fetch APIでデータを取得するプロミスを返す
 *
 * @param {ResourceObj<T>} props - リクエスト情報
 * @param {string} props.url - リクエストURL
 * @param {('GET'|'POST'|'PUT'|'PATCH'|'DELETE')} [props.method='GET'] - HTTPメソッド
 * @param {object} [props.body] - リクエストボディ
 * @param {HeadersInit} [props.headers] - リクエストヘッダー
 * @param {(response: Response) => Promise<T>} [props.takeData] - レスポンスからデータを抽出する関数
 * @returns {Promise<T|null>} データを含むプロミス、エラー時は再スローを行う
 *     (2xx 以外は ApiError。code は problemCodeOf(error) で取り出す)
*/
export const requestFetch = async <T>({ url, method = 'GET', body, headers, takeData = takeDataDef }: ResourceObj<T>): Promise<T | null> => {
    const request = generateRequestObject({ url, method, body, headers });
    return fetch(request).then(async (res) => {
        // エラーステータスは ApiError (Problem Details を problem に保持) として送出する
        if (!res.ok) throw await toApiError(res);
        return takeData(res);
    }).catch((error) => {
        console.error('Fetch error:', error.message);
        throw error;
    });
};
