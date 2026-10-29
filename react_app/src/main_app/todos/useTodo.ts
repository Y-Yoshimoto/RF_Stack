/**
 * @description:
 * AP の ToDo の詳細 (説明・permissions を含む) と ETag を取得・保持するカスタムフック
 * - permissions は画面のボタンの出し分けに使う (サーバーも更新時に判定する)。target を useTodoActions に渡すと、不可の操作は API を呼ばずに弾く
 * - 変更操作の応答は常に詳細 (TodoDetail) のため、applyUpdate で取り直さずに表示・ETag・permissions を新しくする
 * - 閲覧できない・削除済み・他テナントの ToDo は 404 todo_not_found (区別しない)
 * - 412 のときは refresh で表示を保ったまま最新を取り直す (AP-UX-07)。未保存の入力は useRebasedDraft で残す
*/
import { useMemo } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { TodoDetail, TodoPermissions } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { fetchTodo } from '@/main_app/api/todos';
import type { WithEtag } from '@/shared/api/etag';
import { useVersionedResource } from '@/shared/hooks/useVersionedResource';
import { needsOrganizationReselect, todoTargetOf, type TodoTarget } from './todo_changes';

/**
 * ToDo の変更操作の結果 (useTodoActions の onUpdated で通知される)。
 * - create / update / change_status / set_assignees: 変更後の詳細 (permissions を含む) と新しい ETag
 * - delete: 削除した ToDo の ID (以降この ToDo の API は 404)
 */
export type TodoActionUpdate =
    | { action: 'create' | 'update' | 'change_status' | 'set_assignees'; todo: TodoDetail; etag: string }
    | { action: 'delete'; todo_id: string };

/**
 * ToDo の詳細の状態と操作。
 */
export type TodoDetailState = {
    status: 'loading' | 'success' | 'error';
    /** 詳細 (取得前・失敗時は null)。applyUpdate で反映した更新を含む。 */
    todo: TodoDetail | null;
    /** 保持している ETag (取得前・失敗時は null)。 */
    etag: string | null;
    /** 操作者の権限 (取得前・失敗時は null)。 */
    permissions: TodoPermissions | null;
    /** useTodoActions に渡す操作の対象 (取得前・失敗時は null)。 */
    target: TodoTarget | null;
    /** 公開先組織がすべて削除され、再指定を促すべき (AP-VIS-08)。 */
    needs_organization_reselect: boolean;
    /** 取得の失敗 (status === 'error' のとき。404 todo_not_found)。 */
    error: AppErrorInfo | null;
    /** 取り直す (取得中は status が loading になる)。 */
    reload: () => void;
    /**
     * 表示を保ったまま取り直す (status は success のまま)。412・403 todo_operation_forbidden など requires_reload のときに使う。
     * 成功すれば true。失敗すれば false で、表示は前のまま (refresh_error。404 なら削除された・閲覧できなくなった)。
     */
    refresh: () => Promise<boolean>;
    /** refresh の取得中。 */
    is_refreshing: boolean;
    /** 最後の refresh の失敗。 */
    refresh_error: AppErrorInfo | null;
    /** 変更操作の結果を反映する (useTodoActions の onUpdated につなぐ)。別の ToDo への更新・削除は無視する (削除後は画面を離れること)。 */
    applyUpdate: (update: TodoActionUpdate) => void;
};

/**
 * 詳細に変更操作の結果を重ねる関数 (応答は詳細そのものなので置き換える)
 * @param {WithEtag<TodoDetail>} current 現在の詳細
 * @param {TodoActionUpdate} update 変更操作の結果
 * @returns {WithEtag<TodoDetail>} 反映後の詳細
*/
export const mergeTodoUpdate = (current: WithEtag<TodoDetail>, update: TodoActionUpdate): WithEtag<TodoDetail> => {
    if (update.action === 'delete' || update.todo.id !== current.body.id) return current;
    return { body: update.todo, etag: update.etag };
};

/**
 * AP の ToDo の詳細を取得するカスタムフック (AppAuthProvider の内側で使う)
 * todo_id が変わると取り直す。
 * @param {string} todo_id ToDo ID
 * @returns {TodoDetailState} 詳細の状態と操作
*/
export const useTodo = (todo_id: string): TodoDetailState => {
    const client = useAppApiClient();
    const { status, value, etag, error, reload, applyUpdate, refresh, is_refreshing, refresh_error } = useVersionedResource<TodoDetail, TodoActionUpdate>({
        key: `app-todo:${todo_id}`,
        load: () => fetchTodo(client, todo_id),
        merge: mergeTodoUpdate,
        classify: classifyAppError,
    });
    const target = useMemo(() => (value !== null ? todoTargetOf(value, etag) : null), [value, etag]);
    return {
        status,
        todo: value,
        etag,
        permissions: value?.permissions ?? null,
        target,
        needs_organization_reselect: value !== null && needsOrganizationReselect(value),
        error,
        reload,
        applyUpdate,
        refresh,
        is_refreshing,
        refresh_error,
    };
};

export default useTodo;
