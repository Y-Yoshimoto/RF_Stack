// useTodo / useTodoActions のテスト (ETag と If-Match・差分だけの送信・permissions による事前の拒否・412 / 428 / 403 / 404 / 422)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { TodoDetail } from '@/main_app/api/contract';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, ORGANIZATION_ID, OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { ASSIGNEE_TODO_PERMISSIONS, assigneeOf, TODO_ID, todoDetailOf, todoOf } from '@/main_app/testing/todo_test_data';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler, type MockReply } from '@/shared/testing/fetch_mock';
import { todoTargetOf } from './todo_changes';
import { useTodo, type TodoActionUpdate } from './useTodo';
import { useTodoActions, type TodoActionResult } from './useTodoActions';

const DETAIL_KEY = `GET /api/v1/todos/${TODO_ID}`;
const PATCH_KEY = `PATCH /api/v1/todos/${TODO_ID}`;
const DELETE_KEY = `DELETE /api/v1/todos/${TODO_ID}`;
const ASSIGNEES_KEY = `PUT /api/v1/todos/${TODO_ID}/assignees`;
const CREATE_KEY = 'POST /api/v1/todos';
const SECOND_ORGANIZATION_ID = '01900000-0000-7000-8000-00000000b002';

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 詳細の応答を作る関数
 * @param {Partial<TodoDetail>} overrides 上書きする項目
 * @param {number} status ステータス
 * @returns {MockReply} 応答 (ETag は version)
*/
const detailReply = (overrides: Partial<TodoDetail> = {}, status = 200): MockReply => {
    const body = todoDetailOf(overrides);
    return { status, body, headers: { ETag: `"${body.version}"` } };
};

/**
 * 拡張メンバー付きの Problem Details の応答を作る関数
 * @param {number} status ステータス
 * @param {string} code エラーコード
 * @param {Record<string, unknown>} extra 拡張メンバー
 * @returns {MockReply} 応答
*/
const problemWith = (status: number, code: string, extra: Record<string, unknown>): MockReply => {
    const reply = problemReply(status, code);
    return { ...reply, body: { ...(reply.body as object), ...extra } };
};

/**
 * 詳細とアクションを同じ画面で使う形で描画する関数 (詳細の取得を待つ)
 * @param {Record<string, MockHandler>} replies API の応答
 * @param {Partial<TodoDetail>} detail 詳細の上書き
 * @returns {Promise<{ result, spy, onUpdated }>} 描画結果・fetch の spy・成功の通知
*/
const renderDetailWithActions = async (replies: Record<string, MockHandler>, detail: Partial<TodoDetail> = {}) => {
    const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), [DETAIL_KEY]: detailReply(detail), ...replies });
    const onUpdated = vi.fn();
    const { result } = renderHook(() => {
        const todo = useTodo(TODO_ID);
        const actions = useTodoActions({
            onUpdated: (update: TodoActionUpdate) => {
                onUpdated(update);
                todo.applyUpdate(update);
            },
        });
        return { todo, actions };
    }, { wrapper: AppTestProvider });
    await waitFor(() => expect(result.current.todo.status).toBe('success'));
    return { result, spy, onUpdated };
};

/**
 * 詳細から作った操作の対象を返す関数 (取得前は失敗にする)
 * @param {{ todo: { target: ReturnType<typeof todoTargetOf> | null } }} current 描画結果の現在値
 * @returns {ReturnType<typeof todoTargetOf>} 対象
*/
const targetOf = (current: { todo: { target: ReturnType<typeof todoTargetOf> | null } }) => {
    if (current.todo.target === null) throw new Error('詳細が未取得です');
    return current.todo.target;
};

const writeKeys = (spy: ReturnType<typeof mockFetch>) => calledKeys(spy).filter((key) => !key.startsWith('GET '));

describe('useTodo', () => {
    it('詳細・ETag・permissions・操作の対象を取得する。ETag ヘッダーが無ければ version から作る', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), [DETAIL_KEY]: { status: 200, body: todoDetailOf({ version: 5, permissions: ASSIGNEE_TODO_PERMISSIONS }) } });
        const { result } = renderHook(() => useTodo(TODO_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.etag).toBe('"5"');
        expect(result.current.permissions).toEqual(ASSIGNEE_TODO_PERMISSIONS);
        expect(result.current.target).toMatchObject({ todo_id: TODO_ID, etag: '"5"' });
        expect(result.current.needs_organization_reselect).toBe(false);
    });

    it('閲覧範囲外・削除済み・他テナントは 404 todo_not_found', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [DETAIL_KEY]: problemReply(404, 'todo_not_found') });
        const { result } = renderHook(() => useTodo(TODO_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.error).toMatchObject({ kind: 'not_found', status: 404, code: 'todo_not_found', requires_reload: false });
        expect(result.current.target).toBeNull();
    });

    it('公開先組織がすべて削除されたら再指定を促す', async () => {
        mockFetch({ [APP_STATUS_KEY]: appStatusReply(), [DETAIL_KEY]: detailReply({ effective_visibility: 'private', organizations: [] }) });
        const { result } = renderHook(() => useTodo(TODO_ID), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.needs_organization_reselect).toBe(true));
    });
});

describe('useTodoActions: ETag と If-Match', () => {
    it('編集画面が全項目を渡しても実際に変わる項目だけを送り、新しい ETag と permissions を詳細に反映する', async () => {
        const { result, spy, onUpdated } = await renderDetailWithActions({
            [PATCH_KEY]: detailReply({ title: '見積もりを送る', due_date: null, version: 4, permissions: ASSIGNEE_TODO_PERMISSIONS }),
        });
        const current = result.current.todo.todo as TodoDetail;
        let outcome: TodoActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.update(targetOf(result.current), {
                title: '見積もりを送る',
                description: current.description,
                due_date: null,
                priority: current.priority,
                status: current.status,
                audience: { visibility: 'organization', organization_ids: [ORGANIZATION_ID] },
            });
        });
        expect(outcome).toMatchObject({ ok: true, action: 'update', etag: '"4"' });
        expect(onUpdated).toHaveBeenCalledTimes(1);
        expect(result.current.todo.etag).toBe('"4"');
        expect(result.current.todo.todo).toMatchObject({ title: '見積もりを送る', due_date: null, version: 4 });
        expect(result.current.todo.permissions).toEqual(ASSIGNEE_TODO_PERMISSIONS);

        const request = calledRequests(spy).find((item) => item.method === 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(request?.headers.get('X-Requested-With')).toBe('rf-stack');
        expect(await request?.clone().json()).toEqual({ title: '見積もりを送る', due_date: null });
        expect(calledKeys(spy).filter((key) => key === DETAIL_KEY)).toHaveLength(1);
    });

    it('閲覧範囲は visibility と organization_ids を同時に送る', async () => {
        const { result, spy } = await renderDetailWithActions({ [PATCH_KEY]: detailReply({ visibility: 'tenant', effective_visibility: 'tenant', organizations: [], version: 4 }) });
        await act(async () => {
            await result.current.actions.update(targetOf(result.current), { audience: { visibility: 'organization', organization_ids: [ORGANIZATION_ID, SECOND_ORGANIZATION_ID] } });
        });
        expect(await calledRequests(spy).find((item) => item.method === 'PATCH')?.clone().json()).toEqual({ visibility: 'organization', organization_ids: [ORGANIZATION_ID, SECOND_ORGANIZATION_ID] });
        expect(result.current.todo.todo?.visibility).toBe('tenant');
    });

    it('412 todo_version_conflict は再取得を促す失敗にし、ETag は変えない。reload で取り直せる', async () => {
        let detail_calls = 0;
        const { result } = await renderDetailWithActions({
            [DETAIL_KEY]: () => {
                detail_calls += 1;
                return detailReply({ version: 2 + detail_calls });
            },
            [PATCH_KEY]: problemReply(412, 'todo_version_conflict'),
        });
        let outcome: TodoActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.changeStatus(targetOf(result.current), 'done');
        });
        expect(outcome?.ok).toBe(false);
        expect(result.current.actions.failure).toMatchObject({ action: 'change_status', todo_id: TODO_ID, kind: 'version_conflict', status: 412, code: 'todo_version_conflict', requires_reload: true, operation: null });
        expect(result.current.todo.etag).toBe('"3"');
        act(() => result.current.todo.reload());
        await waitFor(() => expect(result.current.todo.etag).toBe('"4"'));
    });

    it('428 は precondition_required (再取得を促す)。ETag が無ければ API を呼ばない', async () => {
        const { result, spy } = await renderDetailWithActions({ [DELETE_KEY]: problemReply(428, 'precondition_required') });
        await act(async () => {
            await result.current.actions.remove(targetOf(result.current));
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'delete', kind: 'precondition_required', status: 428, requires_reload: true });
        await act(async () => {
            await result.current.actions.setAssignees({ ...targetOf(result.current), etag: null }, []);
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'set_assignees', kind: 'precondition_required', status: null, requires_reload: true });
        expect(writeKeys(spy)).toEqual([DELETE_KEY]);
    });

    it('担当者の置き換えは PUT に If-Match を付け、重複を除いて送る', async () => {
        const { result, spy } = await renderDetailWithActions({ [ASSIGNEES_KEY]: detailReply({ assignees: [assigneeOf(), assigneeOf({ user_id: SELF_USER_ID })], version: 4 }) });
        await act(async () => {
            await result.current.actions.setAssignees(targetOf(result.current), [OTHER_USER_ID, SELF_USER_ID, SELF_USER_ID]);
        });
        const request = calledRequests(spy).find((item) => item.method === 'PUT');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.clone().json()).toEqual({ user_ids: [OTHER_USER_ID, SELF_USER_ID] });
        expect(result.current.todo.todo?.assignees.map((assignee) => assignee.user_id)).toEqual([OTHER_USER_ID, SELF_USER_ID]);
        expect(result.current.todo.etag).toBe('"4"');
    });

    it('削除は 204 (本文なし) を成功として通知する', async () => {
        const { result, onUpdated } = await renderDetailWithActions({ [DELETE_KEY]: { status: 204, content_type: 'text/plain' } });
        let outcome: TodoActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.remove(targetOf(result.current));
        });
        expect(outcome).toEqual({ ok: true, action: 'delete', todo_id: TODO_ID });
        expect(onUpdated).toHaveBeenCalledWith({ action: 'delete', todo_id: TODO_ID });
    });

    it('作成は 201 の詳細と ETag を通知し、別の ToDo の作成は詳細に影響しない', async () => {
        const { result, spy, onUpdated } = await renderDetailWithActions({ [CREATE_KEY]: { status: 201, body: todoDetailOf({ id: 'new', title: '新規', version: 1 }), headers: { ETag: '"1"', Location: '/api/v1/todos/new' } } });
        await act(async () => {
            await result.current.actions.create({ title: '新規', visibility: 'tenant', organization_ids: [ORGANIZATION_ID] });
        });
        expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ action: 'create', etag: '"1"', todo: expect.objectContaining({ id: 'new' }) }));
        expect(await calledRequests(spy).find((item) => item.method === 'POST')?.clone().json()).toEqual({ title: '新規', visibility: 'tenant' });
        expect(result.current.todo.todo?.id).toBe(TODO_ID);
    });
});

describe('useTodoActions: permissions と API の拒否', () => {
    it('担当者 (permissions) は項目の変更・閲覧範囲・削除を API を呼ばずに forbidden にし、operation を返す', async () => {
        const { result, spy } = await renderDetailWithActions({}, { permissions: ASSIGNEE_TODO_PERMISSIONS, created_by: OTHER_USER_ID });
        let outcome: TodoActionResult | undefined;
        await act(async () => {
            outcome = await result.current.actions.update(targetOf(result.current), { title: 'x' });
        });
        expect(outcome).toMatchObject({ ok: false, failure: { action: 'update', kind: 'forbidden', status: null, code: 'todo_operation_forbidden', operation: 'edit_fields', requires_reload: false } });
        await act(async () => {
            await result.current.actions.update(targetOf(result.current), { audience: { visibility: 'tenant', organization_ids: [] } });
        });
        expect(result.current.actions.failure).toMatchObject({ operation: 'change_visibility' });
        await act(async () => {
            await result.current.actions.remove(targetOf(result.current));
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'delete', operation: 'delete' });
        expect(writeKeys(spy)).toEqual([]);
    });

    it('担当者でも、全項目を渡した編集でステータスだけが変わるなら API を呼ぶ', async () => {
        const { result, spy } = await renderDetailWithActions({ [PATCH_KEY]: detailReply({ status: 'done', version: 4, permissions: ASSIGNEE_TODO_PERMISSIONS }) }, { permissions: ASSIGNEE_TODO_PERMISSIONS });
        const current = result.current.todo.todo as TodoDetail;
        await act(async () => {
            await result.current.actions.update(targetOf(result.current), { title: current.title, priority: current.priority, status: 'done' });
        });
        expect(result.current.actions.failure).toBeNull();
        expect(await calledRequests(spy).find((item) => item.method === 'PATCH')?.clone().json()).toEqual({ status: 'done' });
    });

    it('変わる項目が無ければ API を呼ばずに invalid_input', async () => {
        const { result, spy } = await renderDetailWithActions({});
        await act(async () => {
            await result.current.actions.changeStatus(targetOf(result.current), 'open');
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'change_status', kind: 'invalid_input', status: null });
        expect(writeKeys(spy)).toEqual([]);
    });

    it('一覧の要素 (permissions なし) は API に任せ、403 todo_operation_forbidden は operation 付き・再取得を促す失敗にする', async () => {
        const { result, spy } = await renderDetailWithActions({ [PATCH_KEY]: problemWith(403, 'todo_operation_forbidden', { operation: 'edit_fields' }) });
        await act(async () => {
            await result.current.actions.update(todoTargetOf(todoOf()), { priority: 'high' });
        });
        expect(writeKeys(spy)).toEqual([PATCH_KEY]);
        expect(calledRequests(spy).find((item) => item.method === 'PATCH')?.headers.get('If-Match')).toBe('"3"');
        expect(result.current.actions.failure).toMatchObject({ kind: 'forbidden', status: 403, code: 'todo_operation_forbidden', operation: 'edit_fields', requires_reload: true });
    });

    it('404 todo_not_found (操作中に削除された・閲覧できなくなった) は not_found', async () => {
        const { result } = await renderDetailWithActions({ [PATCH_KEY]: problemReply(404, 'todo_not_found') });
        await act(async () => {
            await result.current.actions.changeStatus(targetOf(result.current), 'done');
        });
        expect(result.current.actions.failure).toMatchObject({ kind: 'not_found', code: 'todo_not_found', requires_reload: false });
    });

    it('422 invalid_todo_assignees は拡張メンバー user_ids と errors[].code (inactive) を参照できる', async () => {
        const { result } = await renderDetailWithActions({
            [ASSIGNEES_KEY]: problemWith(422, 'invalid_todo_assignees', { user_ids: [SELF_USER_ID], errors: [{ field: 'user_ids', code: 'inactive', message: 'x' }] }),
        });
        await act(async () => {
            await result.current.actions.setAssignees(targetOf(result.current), [OTHER_USER_ID, SELF_USER_ID]);
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'set_assignees', kind: 'invalid_input', code: 'invalid_todo_assignees', requires_reload: false });
        expect(result.current.actions.failure?.problem?.user_ids).toEqual([SELF_USER_ID]);
        expect(result.current.actions.failure?.problem?.errors?.[0].code).toBe('inactive');
    });

    it('organization で公開先組織が無い作成・担当者の上限超過は API を呼ばずに invalid_input', async () => {
        const { result, spy } = await renderDetailWithActions({});
        await act(async () => {
            await result.current.actions.create({ title: 'x', visibility: 'organization', organization_ids: [] });
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'create', todo_id: null, kind: 'invalid_input', code: 'invalid_todo_input' });
        await act(async () => {
            await result.current.actions.setAssignees(targetOf(result.current), Array.from({ length: 21 }, (_, index) => `u${index}`));
        });
        expect(result.current.actions.failure).toMatchObject({ action: 'set_assignees', kind: 'invalid_input', status: null });
        expect(writeKeys(spy)).toEqual([]);
    });
});
