/**
 * @description:
 * AP の ToDo の変更操作 (作成・更新・ステータス変更・担当者の置き換え・削除) のカスタムフック
 *
 * - tenant_admin / member のどちらも使える。操作の可否は ToDo ごとの permissions で決まる (ToDoApp.md §3・§9.3)。
 *   対象が詳細 (useTodo の target) なら、permissions で不可の操作は API を呼ばずに失敗 (kind: forbidden、code: todo_operation_forbidden、operation) にする。
 *   一覧の要素から作った対象 (permissions なし) は確かめずに API に任せる (403 todo_operation_forbidden)
 * - 更新は「実際に値が変わる項目」だけを送り、その項目で権限を確かめる (編集画面が全項目を渡しても、担当者のステータス変更は通る)。
 *   変わる項目が無ければ API を呼ばずに失敗 (kind: invalid_input) にする。画面は diffTodoChanges で保存ボタンを出し分けられる
 * - 更新・担当者の置き換え・削除は保持している ETag を If-Match に付ける。ETag が無ければ API を呼ばずに失敗 (kind: precondition_required)。
 *   412 / 428 / API の 403 todo_operation_forbidden は requires_reload の失敗になる (useTodo の reload で取り直してやり直す)
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
*/
import { useCallback } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { TodoCreate, TodoOperation, TodoStatus } from '@/main_app/api/contract';
import { AppGuardError, classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { createTodo, deleteTodo, replaceTodoAssignees, updateTodo } from '@/main_app/api/todos';
import { useActionRunner, type ActionOutcome } from '@/shared/hooks/useActionRunner';
import {
    assigneesGuardOf,
    createGuardOf,
    diffTodoChanges,
    forbiddenOperationOf,
    removeGuardOf,
    toTodoCreate,
    toTodoUpdate,
    updateGuardOf,
    type TodoChanges,
    type TodoTarget,
} from './todo_changes';
import type { TodoActionUpdate } from './useTodo';

/**
 * 変更操作の種類。
 */
export type TodoActionName = TodoActionUpdate['action'];

/**
 * 変更操作の失敗。
 */
export type TodoActionFailure = AppErrorInfo & {
    action: TodoActionName;
    /** 対象の ToDo ID (作成では null)。 */
    todo_id: string | null;
    /** 権限が無く拒否された操作 (API の 403 の operation、または API を呼ばずに弾いた操作。それ以外は null)。 */
    operation: TodoOperation | null;
};

/**
 * 変更操作の結果。
 */
export type TodoActionResult = ({ ok: true } & TodoActionUpdate) | { ok: false; failure: TodoActionFailure };

export type UseTodoActionsOptions = {
    /** 成功時に呼ばれる (useTodo の applyUpdate、一覧の replaceItem / removeItem / reload、アクティビティの reload につなぐ)。 */
    onUpdated?: (update: TodoActionUpdate) => void;
};

/**
 * 変更操作の状態と操作。
 */
export type TodoActionsState = {
    /** 実行中の操作 (無ければ null)。 */
    pending: TodoActionName | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: TodoActionFailure | null;
    clearFailure: () => void;
    /** ToDo を作成する (誰でも可。organization では公開先組織が 1 つ以上必要。担当者は最大 20 人)。 */
    create: (input: TodoCreate) => Promise<TodoActionResult>;
    /** 項目・ステータス・閲覧範囲 (audience) を更新する (実際に変わる項目だけを送る。target.etag を If-Match に付ける)。 */
    update: (target: TodoTarget, changes: TodoChanges) => Promise<TodoActionResult>;
    /** ステータスだけを変える (担当者向けの近道。can_change_status が必要)。 */
    changeStatus: (target: TodoTarget, status: TodoStatus) => Promise<TodoActionResult>;
    /** 担当者を user_ids に置き換える (全置換。can_change_assignees が必要。存在しない・無効なユーザーの新規割り当ては 422 invalid_todo_assignees)。 */
    setAssignees: (target: TodoTarget, user_ids: readonly string[]) => Promise<TodoActionResult>;
    /** ToDo を削除する (論理削除。can_delete が必要)。 */
    remove: (target: TodoTarget) => Promise<TodoActionResult>;
};

const busyError = () => new AppGuardError('action_in_progress');
const toFailure = (info: AppErrorInfo, action: TodoActionName, todo_id: string | null): TodoActionFailure => ({ ...info, action, todo_id, operation: forbiddenOperationOf(info) });

/**
 * AP の ToDo の変更操作のカスタムフック (AppAuthProvider の内側で使う)
 * @param {UseTodoActionsOptions} options 成功時の通知
 * @returns {TodoActionsState} 状態と操作
*/
export const useTodoActions = ({ onUpdated }: UseTodoActionsOptions = {}): TodoActionsState => {
    const client = useAppApiClient();
    const { pending, failure, clearFailure, execute } = useActionRunner<TodoActionName, TodoActionFailure>({ classify: classifyAppError, toFailure, busyError });

    const finish = useCallback((outcome: ActionOutcome<TodoActionUpdate, TodoActionFailure>): TodoActionResult => {
        if (!outcome.ok) return outcome;
        onUpdated?.(outcome.value);
        return { ok: true, ...outcome.value };
    }, [onUpdated]);

    const create = useCallback(async (input: TodoCreate) => finish(await execute<TodoActionUpdate>({
        action: 'create',
        target_id: null,
        precheck: () => createGuardOf(input),
        run: async () => {
            const { body, etag } = await createTodo(client, toTodoCreate(input));
            return { action: 'create', todo: body, etag };
        },
    })), [execute, finish, client]);

    /**
     * 更新を実行する関数 (update と changeStatus で共有する)
     * @param {'update' | 'change_status'} action 操作の種類
     * @param {TodoTarget} target 対象
     * @param {TodoChanges} changes 変更内容
     * @returns {Promise<TodoActionResult>} 結果
    */
    const patch = useCallback(async (action: 'update' | 'change_status', target: TodoTarget, changes: TodoChanges) => {
        const diff = diffTodoChanges(target.current, changes);
        return finish(await execute<TodoActionUpdate>({
            action,
            target_id: target.todo_id,
            precheck: () => updateGuardOf(target, diff),
            run: async () => {
                const { body, etag } = await updateTodo(client, target.todo_id, toTodoUpdate(diff), target.etag ?? '');
                return { action, todo: body, etag };
            },
        }));
    }, [execute, finish, client]);

    const update = useCallback((target: TodoTarget, changes: TodoChanges) => patch('update', target, changes), [patch]);
    const changeStatus = useCallback((target: TodoTarget, status: TodoStatus) => patch('change_status', target, { status }), [patch]);

    const setAssignees = useCallback(async (target: TodoTarget, user_ids: readonly string[]) => finish(await execute<TodoActionUpdate>({
        action: 'set_assignees',
        target_id: target.todo_id,
        precheck: () => assigneesGuardOf(target, user_ids),
        run: async () => {
            const { body, etag } = await replaceTodoAssignees(client, target.todo_id, user_ids, target.etag ?? '');
            return { action: 'set_assignees', todo: body, etag };
        },
    })), [execute, finish, client]);

    const remove = useCallback(async (target: TodoTarget) => finish(await execute<TodoActionUpdate>({
        action: 'delete',
        target_id: target.todo_id,
        precheck: () => removeGuardOf(target),
        run: async () => {
            await deleteTodo(client, target.todo_id, target.etag ?? '');
            return { action: 'delete', todo_id: target.todo_id };
        },
    })), [execute, finish, client]);

    return { pending, failure, clearFailure, create, update, changeStatus, setAssignees, remove };
};

export default useTodoActions;
