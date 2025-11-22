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
 * @returns {request: Request} リクエストオブジェクト
*/
export const generateRequestObject = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>) => {
    return new Request(url, {
        method: method,
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(body),
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
 * @param {('GET'|'POST'|'PUT'|'DELETE')} [props.method='GET'] - HTTPメソッド
 * @param {object} [props.body] - リクエストボディ
 * @param {HeadersInit} [props.headers] - リクエストヘッダー
 * @param {(response: Response) => Promise<T>} [props.takeData] - レスポンスからデータを抽出する関数
 * @returns {Promise<T|null>} データを含むプロミス、エラー時は再スローを行う
*/
export const requestFetch = async <T>({ url, method = 'GET', body, headers, takeData = takeDataDef }: ResourceObj<T>): Promise<T | null> => {
    const request = generateRequestObject({ url, method, body, headers });
    return fetch(request).then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return takeData(res);
    }).catch((error) => {
        console.error('Fetch error:', error.message);
        throw error;
    });
};
