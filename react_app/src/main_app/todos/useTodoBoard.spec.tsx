// useTodoBoard のテスト (列ごとの include_total・楽観的な移動・失敗時の戻し・412 で 2 列を取り直す)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { TodoStatus } from '@/main_app/api/contract';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply } from '@/main_app/testing/app_test_support';
import { todoDetailOf, todoOf } from '@/main_app/testing/todo_test_data';
import { calledRequests, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { useTodoBoard, type TodoBoardMoveResult } from './useTodoBoard';

const LIST_KEY = 'GET /api/v1/todos';

afterEach(() => {
    vi.restoreAllMocks();
});

const COLUMN_ITEMS: Record<TodoStatus, string[]> = { open: ['a', 'b'], in_progress: ['c'], done: [] };

/**
 * 列ごとの一覧の応答 (status の絞り込みで返す。include_total のときだけ total を返す)
 * @param {Request} request リクエスト
 * @returns {MockReply} 応答
*/
const columnReply = (request: Request): MockReply => {
    const params = new URL(request.url).searchParams;
    const status = params.get('status') as TodoStatus;
    const ids = COLUMN_ITEMS[status];
    return { status: 200, body: { items: ids.map((id) => todoOf({ id, status })), next_cursor: null, total: params.get('include_total') === 'true' ? ids.length : null } };
};

const listRequests = (spy: ReturnType<typeof mockFetch>) => calledRequests(spy).filter((request) => request.method === 'GET' && new URL(request.url).pathname === '/api/v1/todos');
const idsOf = (items: { id: string }[]) => items.map((item) => item.id);

/**
 * ボードを描画して 3 列の取得を待つ関数
 * @param {MockReply | ((request: Request) => MockReply)} patch_reply PATCH の応答
 * @returns {Promise<{ result, spy }>} 描画結果と fetch の spy
*/
const renderBoard = async (patch_reply: MockReply | ((request: Request) => MockReply)) => {
    const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), [LIST_KEY]: columnReply, 'PATCH /api/v1/todos/a': patch_reply, 'PATCH /api/v1/todos/b': patch_reply });
    const { result } = renderHook(() => useTodoBoard({ scope: 'all', status: ['done'], sort: 'due_date' }), { wrapper: AppTestProvider });
    await waitFor(() => expect(Object.values(result.current.columns).every((column) => column.status === 'success')).toBe(true));
    return { result, spy };
};

describe('useTodoBoard', () => {
    it('ステータスごとに 3 列を取得する (絞り込みのステータスは列のものに置き換え、先頭ページで include_total)', async () => {
        const { result, spy } = await renderBoard({ status: 500 });
        expect(listRequests(spy).map((request) => new URL(request.url).searchParams.toString()).sort()).toEqual([
            'status=done&sort=due_date&include_total=true',
            'status=in_progress&sort=due_date&include_total=true',
            'status=open&sort=due_date&include_total=true',
        ]);
        expect(idsOf(result.current.columns.open.items)).toEqual(['a', 'b']);
        expect(result.current.columns.open.total).toBe(2);
        expect(result.current.columns.done.total).toBe(0);
    });

    it('移動は楽観的に列を移し、成功したら応答で置き換える (総件数も増減する)', async () => {
        const { result, spy } = await renderBoard({ status: 200, body: todoDetailOf({ id: 'a', status: 'in_progress', version: 4 }), headers: { ETag: '"4"' } });
        let moving: Promise<TodoBoardMoveResult> = Promise.resolve({ ok: true, todo: null });
        act(() => {
            moving = result.current.moveCard(result.current.columns.open.items[0], 'in_progress');
        });
        expect(idsOf(result.current.columns.open.items)).toEqual(['b']);
        expect(idsOf(result.current.columns.in_progress.items)).toEqual(['a', 'c']);
        expect(result.current.columns.in_progress.items[0].status).toBe('in_progress');
        expect(result.current.moving_id).toBe('a');

        let outcome: TodoBoardMoveResult | null = null;
        await act(async () => {
            outcome = await moving;
        });
        expect(outcome).toMatchObject({ ok: true, todo: { id: 'a', status: 'in_progress' } });
        expect(result.current.moving_id).toBeNull();
        expect(result.current.columns.in_progress.items[0].version).toBe(4);
        expect([result.current.columns.open.total, result.current.columns.in_progress.total]).toEqual([1, 2]);

        const patch = calledRequests(spy).find((request) => request.method === 'PATCH');
        expect(patch?.headers.get('If-Match')).toBe('"3"');
        expect(await patch?.json()).toEqual({ status: 'in_progress' });
        // 成功では取り直さない
        expect(listRequests(spy)).toHaveLength(3);
    });

    it('失敗したら元の列の元の位置に戻し、failure を返す (422 などでは取り直さない)', async () => {
        const { result, spy } = await renderBoard(problemReply(422, 'invalid_todo_input'));
        let outcome: TodoBoardMoveResult | null = null;
        await act(async () => {
            outcome = await result.current.moveCard(result.current.columns.open.items[1], 'done');
        });
        expect(outcome).toMatchObject({ ok: false, failure: { action: 'change_status', kind: 'invalid_input' } });
        expect(idsOf(result.current.columns.open.items)).toEqual(['a', 'b']);
        expect(idsOf(result.current.columns.done.items)).toEqual([]);
        expect([result.current.columns.open.total, result.current.columns.done.total]).toEqual([2, 0]);
        expect(result.current.failure?.kind).toBe('invalid_input');
        expect(listRequests(spy)).toHaveLength(3);
    });

    it('412 では戻したうえで、移動元と移動先の 2 列を取り直す', async () => {
        const { result, spy } = await renderBoard(problemReply(412, 'todo_version_conflict'));
        await act(async () => {
            await result.current.moveCard(result.current.columns.open.items[1], 'in_progress');
        });
        expect(result.current.failure?.kind).toBe('version_conflict');
        await waitFor(() => expect(listRequests(spy)).toHaveLength(5));
        const reloaded = listRequests(spy).slice(3).map((request) => new URL(request.url).searchParams.get('status')).sort();
        expect(reloaded).toEqual(['in_progress', 'open']);
        await waitFor(() => expect(idsOf(result.current.columns.open.items)).toEqual(['a', 'b']));
    });

    it('同じ列への移動は何もしない', async () => {
        const { result, spy } = await renderBoard({ status: 500 });
        let outcome: TodoBoardMoveResult | null = null;
        await act(async () => {
            outcome = await result.current.moveCard(result.current.columns.open.items[0], 'open');
        });
        expect(outcome).toEqual({ ok: true, todo: null });
        expect(calledRequests(spy).some((request) => request.method === 'PATCH')).toBe(false);
    });
});
