// 共通関数群定義ファイル
//// 共通型定義読み込み
import { ResourceObj } from './type';

// Fetch API共通関数群
//// レスポンスからjsonデータを抽出する関数
export const takeDataDef = (r: Response) => r.json();
/**
 * リクエストオブジェクト生成関数
 * https://developer.mozilla.org/ja/docs/Web/API/Request
 * @param {ResourceObj<T>} param0 リクエスト情報
 * @returns {request: Request, requestKey: string} リクエストオブジェクトと一意のキー文字列
*/
export const generateRequestObjectAndKey = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>) => {
    const bodyString = JSON.stringify(body);
    const requestKey = `${url}-${method}-${bodyString}-${JSON.stringify(headers)}`;
    const request = new Request(url, {
        method: method,
        headers: { 'Content-Type': 'application/json', ...headers },
        body: body ? bodyString : undefined,
    });
    return { request, requestKey };
};

/**
 * requestFetch リクエスト情報を受け取り、Fetchプロミスを返す
 *
 * @param {ResourceObj<T>} props - リクエスト情報
 * @param {string} props.url - リクエストURL
 * @param {('GET'|'POST'|'PUT'|'DELETE')} [props.method='GET'] - HTTPメソッド
 * @param {object} [props.body] - リクエストボディ
 * @param {HeadersInit} [props.headers] - リクエストヘッダー
 * @param {(response: Response) => Promise<T>} [props.takeData] - レスポンスからデータを抽出する関数
 * @returns {Promise<T|null>} データを含むプロミス、エラー時は再スローを行う
*/
export const requestFetch = async <T>({ url, method = 'GET', body, headers, takeData = takeDataDef }: ResourceObj<T>): Promise<T | null> => {
    const { request } = generateRequestObjectAndKey({ url, method, body, headers });
    return fetch(request).then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return takeData(res);
    }).catch((error) => {
        console.error('Fetch error:', error.message);
        throw error;
    });
};
