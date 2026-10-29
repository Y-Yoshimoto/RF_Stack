// テスト用: fetch を「メソッド + パス」単位でモックする補助関数 (アプリのコードからは import しない)
import { vi } from 'vitest';

/** モックの応答 */
export type MockReply = {
    status: number;
    body?: unknown;
    /** 既定: 2xx は application/json、それ以外は application/problem+json */
    content_type?: string;
    /** 追加のレスポンスヘッダー (ETag など) */
    headers?: Record<string, string>;
};

/** 本文を持てないステータス */
const NULL_BODY_STATUSES: readonly number[] = [204, 205, 304];

/** 応答、またはリクエストから応答を決める関数 (クエリ・ヘッダー・呼び出し回数で応答を変える場合) */
export type MockHandler = MockReply | ((request: Request) => MockReply);

/**
 * Problem Details の応答を作る関数
 * @param {number} status ステータス
 * @param {string} code エラーコード
 * @returns {MockReply} 応答
*/
export const problemReply = (status: number, code: string): MockReply => ({
    status,
    body: { type: `about:blank#${code}`, title: code, status, detail: code, instance: '/', code, errors: [] },
});

/**
 * fetch をモックする関数
 * キーは `GET /api/auth/app/status` の形 (メソッド + パス。クエリは含めない)。登録の無いリクエストは reject する。
 * @param {Record<string, MockHandler>} replies 応答 (またはリクエストから応答を決める関数) の対応表
 * @returns {ReturnType<typeof vi.spyOn>} spy (呼び出しの確認に使う)
*/
export const mockFetch = (replies: Record<string, MockHandler>) => {
    return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = input instanceof Request ? input : new Request(input, init);
        const key = `${request.method} ${new URL(request.url).pathname}`;
        const handler = replies[key];
        if (!handler) throw new TypeError(`unmocked request: ${key}`);
        const reply = typeof handler === 'function' ? handler(request) : handler;
        const content_type = reply.content_type ?? (reply.status < 300 ? 'application/json' : 'application/problem+json');
        // 204 などの本文を持てないステータスでは本文を付けない (Response の生成が失敗するため)
        const body = NULL_BODY_STATUSES.includes(reply.status) ? null : JSON.stringify(reply.body ?? {});
        return new Response(body, { status: reply.status, headers: { 'Content-Type': content_type, ...reply.headers } });
    });
};

/**
 * fetch のモックへのリクエストの一覧を返す関数 (クエリ・ヘッダーの確認に使う)
 * @param {ReturnType<typeof mockFetch>} spy mockFetch の戻り値
 * @returns {Request[]} リクエスト
*/
export const calledRequests = (spy: ReturnType<typeof mockFetch>): Request[] => {
    return spy.mock.calls.map(([input, init]) => (input instanceof Request ? input : new Request(input, init)));
};

/**
 * fetch のモックへの呼び出しをキー (メソッド + パス) の一覧にする関数
 * @param {ReturnType<typeof mockFetch>} spy mockFetch の戻り値
 * @returns {string[]} 呼び出されたキー
*/
export const calledKeys = (spy: ReturnType<typeof mockFetch>): string[] => {
    return spy.mock.calls.map(([input, init]) => {
        const request = input instanceof Request ? input : new Request(input, init);
        return `${request.method} ${new URL(request.url).pathname}`;
    });
};
