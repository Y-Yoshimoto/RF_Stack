// Problem Details (RFC 9457) の読み取りと requestFetch のエラー変換のテスト
import { describe, it, expect, vi, afterEach } from 'vitest';

import { ApiError, isProblemDetails, problemCodeOf, problemOf, readProblem } from './problem';
import { requestFetch } from './common';

// FastAPI が返す Problem Details の例 (CSRF 検証失敗)
const PROBLEM_BODY = {
    type: 'https://errors.rf-stack.example/csrf-validation-failed',
    title: 'リクエストを受け付けられません',
    status: 403,
    detail: 'リクエストの送信元を確認できませんでした。画面を再読み込みして、もう一度お試しください',
    instance: '/api/auth/app/logout',
    code: 'csrf_validation_failed',
    request_id: '01a17ffd-4ffc-73e3-93f9-c9417b1c3060',
    errors: [],
};

const genProblemResponse = (body: object, status: number, content_type = 'application/problem+json') => {
    return new Response(JSON.stringify(body), { status, statusText: 'Forbidden', headers: { 'Content-Type': content_type } });
};

afterEach(() => {
    vi.restoreAllMocks();
});

describe('Problem Details の読み取り', () => {
    it('problem+json の本文を読み取る', async () => {
        const problem = await readProblem(genProblemResponse(PROBLEM_BODY, 403));
        expect(problem?.code).toBe('csrf_validation_failed');
        expect(problem?.status).toBe(403);
    });

    it('problem+json でない応答は undefined', async () => {
        const problem = await readProblem(genProblemResponse(PROBLEM_BODY, 403, 'application/json'));
        expect(problem).toBeUndefined();
    });

    it('形が合わない本文は undefined', async () => {
        expect(await readProblem(genProblemResponse({ detail: 'Not Found' }, 404))).toBeUndefined();
        expect(isProblemDetails(null)).toBe(false);
        expect(isProblemDetails({ code: 'x', status: '403' })).toBe(false);
    });

    it('拡張メンバーを保持する', async () => {
        const problem = await readProblem(genProblemResponse({ ...PROBLEM_BODY, status: 502, code: 'tenant_provisioning_failed', tenant_id: 't1', step: 'realm' }, 502));
        expect(problem?.tenant_id).toBe('t1');
        expect(problem?.step).toBe('realm');
    });
});

describe('例外からの code の取り出し', () => {
    it('ApiError から code を取り出す', () => {
        const error = new ApiError(403, 'Forbidden', PROBLEM_BODY);
        expect(problemCodeOf(error)).toBe('csrf_validation_failed');
        expect(problemOf(error)?.request_id).toBe(PROBLEM_BODY.request_id);
    });

    it('Problem Details の無い例外は undefined', () => {
        expect(problemCodeOf(new ApiError(500, 'Internal Server Error'))).toBeUndefined();
        expect(problemCodeOf(new Error('Network Error'))).toBeUndefined();
        expect(problemCodeOf(undefined)).toBeUndefined();
    });
});

describe('requestFetch のエラー変換', () => {
    it('エラーステータスは ApiError として送出し、message はステータステキストのまま', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(genProblemResponse(PROBLEM_BODY, 403));
        const error: unknown = await requestFetch({ url: '/api/auth/app/logout', method: 'POST' }).catch((e: unknown) => e);
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(403);
        expect((error as ApiError).message).toBe('Forbidden');
        expect(problemCodeOf(error)).toBe('csrf_validation_failed');
    });

    it('変更系メソッドには CSRF 対策ヘッダーを付与する', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ logout_url: '/' }), { status: 200 }));
        await requestFetch({ url: '/api/auth/app/logout', method: 'POST' });
        const request = fetchMock.mock.calls[0][0] as Request;
        expect(request.headers.get('X-Requested-With')).toBe('rf-stack');
    });

    it('参照系メソッドには CSRF 対策ヘッダーを付与しない', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
        await requestFetch({ url: '/api/v1/me' });
        const request = fetchMock.mock.calls[0][0] as Request;
        expect(request.headers.get('X-Requested-With')).toBeNull();
    });
});
