// ToDo の純粋関数のテスト (URL クエリとの相互変換・API のクエリ・差分・事前の確認・エラー分類・選択肢・アクティビティの payload)
import { describe, expect, it } from 'vitest';
import type { TodoCreate } from '@/main_app/api/contract';
import { AppGuardError, classifyAppError } from '@/main_app/api/errors';
import { buildTodoActivitiesUrl, buildTodoListUrl, normalizeTodoListFilter, toTodoListQuery, type TodoListFilter } from '@/main_app/api/todos';
import { ORGANIZATION_ID, OTHER_USER_ID, SELF_USER_ID, organizationOf, userOf } from '@/main_app/testing/app_test_support';
import { activityOf, ASSIGNEE_TODO_PERMISSIONS, assigneeOf, TODO_ID, todoDetailOf, todoOf } from '@/main_app/testing/todo_test_data';
import { ApiError, type ProblemDetails } from '@/utils/libs/FetchComponents/problem';
import { todoActivityChangesOf, todoActivityCreatedValuesOf, todoActivityDeletedTitleOf, todoActivityIdDeltaOf } from './activity_payload';
import { isIsoDate, parseTodoListSearch, toTodoListSearch } from './list_search';
import {
    assigneesGuardOf,
    createGuardOf,
    diffTodoChanges,
    forbiddenOperationOf,
    needsOrganizationReselect,
    removeGuardOf,
    TodoGuardError,
    todoReadOf,
    todoTargetOf,
    toTodoCreate,
    toTodoUpdate,
    updateGuardOf,
} from './todo_changes';
import { todoAssigneeOptionsOf, todoOrganizationOptionsOf } from './useTodoChoices';

const ORG_2 = '01900000-0000-7000-8000-00000000b002';

/**
 * Problem Details 付きの ApiError を作る関数
 * @param {number} status ステータス
 * @param {string} code エラーコード
 * @param {Partial<ProblemDetails>} extra 追加の項目
 * @returns {ApiError} 例外
*/
const apiErrorOf = (status: number, code: string, extra: Partial<ProblemDetails> = {}) => new ApiError(status, 'x', { type: 'about:blank', title: code, status, detail: code, instance: '/', code, errors: [], ...extra });

/**
 * 弾いた理由を取り出す関数
 * @param {AppGuardError | null} guard 弾く理由
 * @returns {string | null} 理由
*/
const reasonOf = (guard: AppGuardError | null) => guard?.reason ?? null;

describe('URL クエリとの相互変換', () => {
    it('URL クエリを読み取り、正規化した絞り込みにする (複数値はカンマ区切り・既定の順)', () => {
        const filter = parseTodoListSearch(`?scope=assigned&status=done,open,open&priority=high&q=%20見積%20&organization_id=${ORGANIZATION_ID}&assignee_id=${OTHER_USER_ID}&due_before=2026-12-31&due_after=2026-11-01&sort=-due_date`);
        expect(filter).toEqual({
            scope: 'assigned',
            status: ['open', 'done'],
            priority: ['high'],
            q: '見積',
            organization_id: ORGANIZATION_ID,
            assignee_id: OTHER_USER_ID,
            due_before: '2026-12-31',
            due_after: '2026-11-01',
            sort: '-due_date',
        });
    });

    it('不正な値 (未知の値・複数キーの sort・UUID や日付の形式違い・存在しない日付) は捨てる', () => {
        expect(parseTodoListSearch('scope=everyone&status=open,closed&priority=urgent&organization_id=abc&assignee_id=1&due_before=2026-02-30&due_after=20261101&sort=due_date,-priority')).toEqual({ status: ['open'] });
        expect(isIsoDate('2028-02-29')).toBe(true);
        expect(isIsoDate('2026-02-29')).toBe(false);
    });

    it('既定値 (scope=all・sort=-created_at)・空の値は省く', () => {
        expect(parseTodoListSearch('scope=all&sort=-created_at&status=&q=%20%20')).toEqual({});
        expect(toTodoListSearch({ scope: 'all', sort: '-created_at', status: [], q: ' ' }).toString()).toBe('');
    });

    it('書き出しは並びを固定し、絞り込み以外のクエリは残す。limit は載せない', () => {
        const search = toTodoListSearch({ sort: 'priority', status: ['in_progress', 'open'], scope: 'mine', limit: 20 }, '?tab=board&status=done&cursor=x');
        expect(search.toString()).toBe('tab=board&cursor=x&scope=mine&status=open%2Cin_progress&sort=priority');
    });

    it('書き出して読み取ると、正規化した絞り込みに戻る', () => {
        const filter: TodoListFilter = { scope: 'shared', status: ['done', 'open'], priority: ['low', 'high'], q: ' a,b ', organization_id: ORGANIZATION_ID, due_after: '2026-01-01', sort: 'updated_at' };
        expect(parseTodoListSearch(toTodoListSearch(filter))).toEqual(normalizeTodoListFilter(filter));
    });
});

describe('一覧 API のクエリ', () => {
    it('絞り込みを API のクエリ名 (assignee_id / organization_id) と固定の順の URL にする', () => {
        expect(buildTodoListUrl(toTodoListQuery({}))).toBe('/api/v1/todos');
        const query = toTodoListQuery({ assignee_id: OTHER_USER_ID, organization_id: ORGANIZATION_ID, status: ['done', 'open'], priority: ['medium'], scope: 'mine', limit: 20, sort: 'due_date' });
        expect(query).toEqual({ limit: 20, scope: 'mine', status: 'open,done', priority: 'medium', organization_id: ORGANIZATION_ID, assignee_id: OTHER_USER_ID, sort: 'due_date' });
        expect(buildTodoListUrl({ ...query, cursor: 'c1' })).toBe(`/api/v1/todos?limit=20&cursor=c1&scope=mine&status=open%2Cdone&priority=medium&organization_id=${ORGANIZATION_ID}&assignee_id=${OTHER_USER_ID}&sort=due_date`);
    });

    it('同じ意味の指定は同じ URL になる (一覧のキーが変わらない)', () => {
        expect(buildTodoListUrl(toTodoListQuery({ scope: 'all', status: ['open', 'open'] }))).toBe(buildTodoListUrl(toTodoListQuery({ status: ['open'] })));
    });

    it('アクティビティの URL', () => {
        expect(buildTodoActivitiesUrl(TODO_ID, {})).toBe(`/api/v1/todos/${TODO_ID}/activities`);
        expect(buildTodoActivitiesUrl(TODO_ID, { limit: 10, cursor: 'c' })).toBe(`/api/v1/todos/${TODO_ID}/activities?limit=10&cursor=c`);
    });
});

describe('diffTodoChanges / toTodoUpdate', () => {
    const current = todoDetailOf();

    it('実際に変わる項目だけを残す (説明の空文字は null と同じ)', () => {
        const all = { title: current.title, description: current.description, due_date: current.due_date, priority: current.priority, status: 'done' as const, audience: { visibility: 'organization' as const, organization_ids: [ORGANIZATION_ID] } };
        expect(diffTodoChanges(current, all)).toEqual({ status: 'done' });
        expect(diffTodoChanges(todoDetailOf({ description: null }), { description: '' })).toEqual({});
        expect(diffTodoChanges(current, { due_date: null })).toEqual({ due_date: null });
    });

    it('閲覧範囲は公開先組織の集合も比べる', () => {
        expect(diffTodoChanges(current, { audience: { visibility: 'organization', organization_ids: [ORGANIZATION_ID, ORGANIZATION_ID] } })).toEqual({});
        expect(diffTodoChanges(current, { audience: { visibility: 'organization', organization_ids: [ORG_2] } })).toHaveProperty('audience');
        expect(diffTodoChanges(todoDetailOf({ visibility: 'tenant', organizations: [] }), { audience: { visibility: 'tenant', organization_ids: [] } })).toEqual({});
    });

    it('一覧の要素 (説明なし) では説明を常に変更とみなし、現在の値が無ければ指定どおり', () => {
        expect(diffTodoChanges(todoOf(), { description: 'x', title: todoOf().title })).toEqual({ description: 'x' });
        expect(diffTodoChanges(null, { title: 'x' })).toEqual({ title: 'x' });
    });

    it('閲覧範囲は visibility と organization_ids を同時に送り、organization 以外では organization_ids を送らない', () => {
        expect(toTodoUpdate({ audience: { visibility: 'organization', organization_ids: [ORGANIZATION_ID, ORG_2, ORGANIZATION_ID] } })).toEqual({ visibility: 'organization', organization_ids: [ORGANIZATION_ID, ORG_2] });
        expect(toTodoUpdate({ audience: { visibility: 'private', organization_ids: [ORGANIZATION_ID] } })).toEqual({ visibility: 'private' });
        expect(toTodoUpdate({ description: '', due_date: null })).toEqual({ description: null, due_date: null });
    });
});

describe('API を呼ぶ前の確認', () => {
    const assignee_target = todoTargetOf(todoDetailOf({ permissions: ASSIGNEE_TODO_PERMISSIONS }), '"3"');

    it('担当者は項目・閲覧範囲・削除を弾かれ、ステータス・担当者の変更は通る', () => {
        const edit = updateGuardOf(assignee_target, { title: 'x', status: 'done' });
        expect(edit).toBeInstanceOf(TodoGuardError);
        expect(edit instanceof TodoGuardError ? edit.operation : null).toBe('edit_fields');
        const audience = updateGuardOf(assignee_target, { audience: { visibility: 'tenant', organization_ids: [] } });
        expect(audience instanceof TodoGuardError ? audience.operation : null).toBe('change_visibility');
        expect(removeGuardOf(assignee_target)).toBeInstanceOf(TodoGuardError);
        expect(updateGuardOf(assignee_target, { status: 'done' })).toBeNull();
        expect(assigneesGuardOf(assignee_target, [])).toBeNull();
    });

    it('一覧の要素 (permissions なし) は権限を確かめず、version から ETag を作る', () => {
        const target = todoTargetOf(todoOf({ version: 7 }));
        expect(target.etag).toBe('"7"');
        expect(updateGuardOf(target, { title: 'x' })).toBeNull();
        expect(removeGuardOf(target)).toBeNull();
    });

    it('変更なし・ETag なし・organization の公開先なし・担当者の上限超過を弾く', () => {
        const target = todoTargetOf(todoDetailOf(), '"3"');
        expect(reasonOf(updateGuardOf(target, {}))).toBe('empty_changes');
        expect(reasonOf(updateGuardOf({ ...target, etag: null }, { title: 'x' }))).toBe('missing_etag');
        expect(reasonOf(updateGuardOf(target, { audience: { visibility: 'organization', organization_ids: [] } }))).toBe('todo_organizations_required');
        expect(reasonOf(assigneesGuardOf(target, [OTHER_USER_ID]))).toBe('empty_changes');
        expect(reasonOf(assigneesGuardOf(target, Array.from({ length: 21 }, (_, index) => `u${index}`)))).toBe('todo_too_many_assignees');
        expect(reasonOf(removeGuardOf({ ...target, etag: null }))).toBe('missing_etag');
    });

    it('作成: organization の公開先なし・担当者の上限超過を弾き、organization 以外では公開先を送らない', () => {
        expect(reasonOf(createGuardOf({ title: 'x', visibility: 'organization' }))).toBe('todo_organizations_required');
        expect(reasonOf(createGuardOf({ title: 'x', assignee_ids: Array.from({ length: 21 }, (_, index) => `u${index}`) }))).toBe('todo_too_many_assignees');
        expect(createGuardOf({ title: 'x' })).toBeNull();
        const input: TodoCreate = { title: 'x', visibility: 'private', organization_ids: [ORGANIZATION_ID], assignee_ids: [OTHER_USER_ID, OTHER_USER_ID] };
        expect(toTodoCreate(input)).toEqual({ title: 'x', visibility: 'private', assignee_ids: [OTHER_USER_ID] });
    });
});

describe('classifyAppError (ToDo)', () => {
    it.each([
        [412, 'todo_version_conflict', 'version_conflict', true],
        [428, 'precondition_required', 'precondition_required', true],
        [403, 'todo_operation_forbidden', 'forbidden', true],
        [403, 'forbidden', 'forbidden', false],
        [404, 'todo_not_found', 'not_found', false],
        [422, 'invalid_todo_input', 'invalid_input', false],
        [422, 'invalid_todo_organizations', 'invalid_input', false],
    ])('%i %s は %s (requires_reload: %s)', (status, code, kind, requires_reload) => {
        expect(classifyAppError(apiErrorOf(status, code))).toMatchObject({ status, code, kind, requires_reload });
    });

    it('422 invalid_todo_assignees の user_ids と errors[].code (not_found / inactive) を参照できる', () => {
        const info = classifyAppError(apiErrorOf(422, 'invalid_todo_assignees', { user_ids: [OTHER_USER_ID], errors: [{ field: 'user_ids', code: 'inactive', message: 'x' }] }));
        expect(info.problem?.user_ids).toEqual([OTHER_USER_ID]);
        expect(info.problem?.errors?.[0].code).toBe('inactive');
    });

    it('拒否された操作は API の operation、または弾いた操作から取り出す', () => {
        expect(forbiddenOperationOf(classifyAppError(apiErrorOf(403, 'todo_operation_forbidden', { operation: 'delete' })))).toBe('delete');
        expect(forbiddenOperationOf(classifyAppError(apiErrorOf(403, 'todo_operation_forbidden', { operation: 'unknown' })))).toBeNull();
        const guarded = classifyAppError(new TodoGuardError('change_status'));
        expect(guarded).toMatchObject({ kind: 'forbidden', status: null, code: 'todo_operation_forbidden', requires_reload: false });
        expect(forbiddenOperationOf(guarded)).toBe('change_status');
        expect(classifyAppError(new AppGuardError('todo_organizations_required'))).toMatchObject({ kind: 'invalid_input', code: 'invalid_todo_input' });
    });
});

describe('詳細の補助', () => {
    it('todoReadOf は説明・permissions を除く', () => {
        expect(todoReadOf(todoDetailOf())).toEqual(todoOf());
    });

    it('公開先組織がすべて削除されたら再指定を促す', () => {
        expect(needsOrganizationReselect(todoOf({ effective_visibility: 'private', organizations: [] }))).toBe(true);
        expect(needsOrganizationReselect(todoOf())).toBe(false);
    });
});

describe('選択肢', () => {
    it('担当者: 無効なユーザーは新規の選択肢から除き、割り当て済みなら残す (一覧に無い担当者も残す)', () => {
        const users = [userOf({ id: SELF_USER_ID, display_name: 'Self' }), userOf({ id: OTHER_USER_ID, is_active: false }), userOf({ id: 'inactive', is_active: false })];
        const assigned = [assigneeOf({ user_id: OTHER_USER_ID, is_active: false }), assigneeOf({ user_id: 'gone', display_name: 'Gone', is_active: false })];
        expect(todoAssigneeOptionsOf(users, assigned)).toEqual([
            { user_id: SELF_USER_ID, display_name: 'Self', is_active: true, is_assigned: false },
            { user_id: OTHER_USER_ID, display_name: 'Taro Yamada', is_active: false, is_assigned: true },
            { user_id: 'gone', display_name: 'Gone', is_active: false, is_assigned: true },
        ]);
    });

    it('公開先組織: 有効な組織と、現在の公開先', () => {
        expect(todoOrganizationOptionsOf([organizationOf(), organizationOf({ id: ORG_2, name: '開発部' })], [{ id: ORG_2, name: '開発部' }, { id: 'old', name: '旧' }])).toEqual([
            { organization_id: ORGANIZATION_ID, name: '営業部', is_selected: false },
            { organization_id: ORG_2, name: '開発部', is_selected: true },
            { organization_id: 'old', name: '旧', is_selected: true },
        ]);
    });
});

describe('アクティビティの payload', () => {
    it('項目の変更・ID の追加と削除・作成時の値・削除時のタイトルを読む', () => {
        expect(todoActivityChangesOf(activityOf({ action: 'updated', payload: { changes: { title: { before: 'a', after: 'b' }, due_date: { before: null, after: '2026-11-01' } } } }))).toEqual([
            { field: 'title', before: 'a', after: 'b' },
            { field: 'due_date', before: null, after: '2026-11-01' },
        ]);
        expect(todoActivityIdDeltaOf(activityOf({ action: 'assignees_changed', payload: { added: [OTHER_USER_ID], removed: [] } }))).toEqual({ added: [OTHER_USER_ID], removed: [] });
        expect(todoActivityIdDeltaOf(activityOf({ action: 'visibility_changed', payload: { organization_ids: { added: [], removed: [ORGANIZATION_ID] } } }))).toEqual({ added: [], removed: [ORGANIZATION_ID] });
        expect(todoActivityCreatedValuesOf(activityOf({ payload: { values: { title: 'x' } } }))).toEqual({ title: 'x' });
        expect(todoActivityDeletedTitleOf(activityOf({ action: 'deleted', payload: { title: 'x' } }))).toBe('x');
    });

    it('形が合わない payload は空として扱う', () => {
        expect(todoActivityChangesOf(activityOf({ action: 'updated', payload: { changes: [1] } }))).toEqual([]);
        expect(todoActivityIdDeltaOf(activityOf({ action: 'deleted', payload: { added: ['x'] } }))).toEqual({ added: [], removed: [] });
        expect(todoActivityDeletedTitleOf(activityOf({ action: 'deleted', payload: {} }))).toBeNull();
    });
});
