// Storybook のストーリー用: AP の API (fetch) を、ストーリーごとの応答に差し替える (アプリ本体・vitest からは import しない)
// 使い方: meta に `beforeEach: appApiBeforeEach` を指定し、ストーリーの parameters.app_api に「メソッド + パス」→ 応答の対応表を渡す。
import type { ReactNode } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppLayout } from '@/main_app/layouts/AppLayout';

/**
 * 応答の定義。
 */
export type StoryApiReply = {
    status: number;
    body?: unknown;
    /** 追加のレスポンスヘッダー (ETag など)。 */
    headers?: Record<string, string>;
    /** true なら応答しない (読み込み中の表示を確認する)。 */
    never_settles?: boolean;
};

/** 応答、またはリクエストから応答を決める関数 */
export type StoryApiHandler = StoryApiReply | ((request: Request) => StoryApiReply);

/** ストーリーの parameters.app_api (キーは `GET /api/v1/users` の形。クエリは含めない) */
export type AppApiStoryParameters = Record<string, StoryApiHandler>;

/**
 * Problem Details の応答を作る関数
 * @param {number} status ステータス
 * @param {string} code エラーコード
 * @param {Record<string, unknown>} extra 拡張メンバー
 * @returns {StoryApiReply} 応答
*/
export const problemStoryReply = (status: number, code: string, extra: Record<string, unknown> = {}): StoryApiReply => ({
    status,
    body: { type: `about:blank#${code}`, title: code, status, detail: `(${code})`, instance: '/', code, errors: [], ...extra },
});

/**
 * ストーリーの実行前に fetch を差し替え、終了時に戻す関数 (meta.beforeEach に指定する)
 * 登録の無いリクエストは 404 の Problem Details を返す。
 * @param {{ parameters: Record<string, unknown> }} context ストーリーの文脈
 * @returns {() => void} 後始末 (fetch を元に戻す)
*/
export const appApiBeforeEach = ({ parameters }: { parameters: Record<string, unknown> }): (() => void) => {
    const replies = (parameters.app_api ?? {}) as AppApiStoryParameters;
    const original = globalThis.fetch;
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = input instanceof Request ? input : new Request(input, init);
        const key = `${request.method} ${new URL(request.url).pathname}`;
        const handler = replies[key];
        if (!handler) return Response.json({ type: 'about:blank#not_found', title: 'not_found', status: 404, detail: `unmocked: ${key}`, instance: '/', code: 'not_found', errors: [] }, { status: 404, headers: { 'Content-Type': 'application/problem+json' } });
        const reply = typeof handler === 'function' ? handler(request) : handler;
        if (reply.never_settles) return new Promise<Response>(() => undefined);
        const content_type = reply.status < 300 ? 'application/json' : 'application/problem+json';
        const body = reply.status === 204 ? null : JSON.stringify(reply.body ?? {});
        return new Response(body, { status: reply.status, headers: { 'Content-Type': content_type, ...reply.headers } });
    };
    return () => {
        globalThis.fetch = original;
    };
};

/**
 * 本番と同じく、AP のレイアウトの Outlet に画面を表示する枠 (子にルートを渡す)
 * @param {{ children: ReactNode }} props `<Route>` の並び
 * @returns {JSX.Element} ルート
*/
export const AppStoryFrame = ({ children }: { children: ReactNode }) => (
    <Routes>
        <Route path="/:tenantCode/*" element={<AppLayout />}>{children}</Route>
    </Routes>
);
