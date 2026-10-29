/**
 * @description:
 * ToDo のコメント (AP-CMT) の一覧と投稿・編集・削除のカスタムフック
 * - 一覧は古い順のカーソル方式 (§10 #19)。todo_id が変わるか reload を呼ぶと先頭ページから取り直す。閲覧できない ToDo は 404 todo_not_found
 * - 投稿は一覧の末尾に差し込む (続きのページがあるときは、最後のページまで読み込むと末尾に並ぶ。useCursorList の insertItem)。
 *   編集は置き換え、削除は除く (取り直さない)
 * - 権限で不可の操作は API を呼ばずに失敗にする: 投稿は options.can_comment (ToDo の permissions)、編集・削除はコメントの permissions。
 *   本文が空・4,000 文字超えも API を呼ばない (kind: invalid_input)
 * - 編集・削除の If-Match はコメントの版 (version)。412 todo_comment_version_conflict / 404 todo_comment_not_found は requires_reload の失敗
 *   (他の人が編集・削除した。reload で取り直す)
 * - コメントの変更は ToDo 本体の ETag を変えない (useTodo の取り直しは不要。コメント数を表示し直す場合は onChanged を使う)
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
*/
import { useCallback } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import { ifMatchOf, type TodoCommentListQuery, type TodoCommentRead, type TodoOperation } from '@/main_app/api/contract';
import { AppGuardError, classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { buildTodoCommentsUrl, createTodoComment, deleteTodoComment, fetchTodoCommentPage, updateTodoComment } from '@/main_app/api/todo_comments';
import { useActionRunner, type ActionOutcome } from '@/shared/hooks/useActionRunner';
import { useCursorList, type CursorListState } from '@/shared/hooks/useCursorList';
import { commentCreateGuardOf, commentRemoveGuardOf, commentUpdateGuardOf } from './comment_changes';
import { forbiddenOperationOf } from './todo_changes';

/**
 * コメントの変更 (onChanged で通知される)。
 */
export type TodoCommentChange = { action: 'create' | 'update'; comment: TodoCommentRead } | { action: 'delete'; comment_id: string };

/** コメントの操作の種類。 */
export type TodoCommentActionName = TodoCommentChange['action'];

/**
 * コメントの操作の失敗。
 */
export type TodoCommentFailure = AppErrorInfo & {
    action: TodoCommentActionName;
    /** 対象のコメント ID (投稿では null)。 */
    comment_id: string | null;
    /** 権限が無く拒否された操作 (edit_comment / delete_comment。投稿の権限なしは null で kind: forbidden)。 */
    operation: TodoOperation | null;
};

/**
 * コメントの操作の結果。
 */
export type TodoCommentResult = ({ ok: true } & TodoCommentChange) | { ok: false; failure: TodoCommentFailure };

export type UseTodoCommentsOptions = {
    /** ToDo の permissions.can_comment (false なら投稿は API を呼ばずに弾く。省略時は API に任せる)。 */
    can_comment?: boolean;
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
    /** 変更に成功したときに呼ばれる (一覧のコメント数の表示し直しなど)。 */
    onChanged?: (change: TodoCommentChange) => void;
};

/**
 * コメントの一覧の状態と操作。
 */
export type TodoCommentsState = CursorListState<TodoCommentRead> & {
    /** 実行中の操作 (無ければ null)。 */
    pending: TodoCommentActionName | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: TodoCommentFailure | null;
    clearFailure: () => void;
    /** 投稿する (本文は入力のまま送る)。 */
    create: (body: string) => Promise<TodoCommentResult>;
    /** 本文を編集する (投稿者のみ)。 */
    update: (comment: TodoCommentRead, body: string) => Promise<TodoCommentResult>;
    /** 削除する (投稿者・tenant_admin)。 */
    remove: (comment: TodoCommentRead) => Promise<TodoCommentResult>;
};

const busyError = () => new AppGuardError('action_in_progress');
const toFailure = (info: AppErrorInfo, action: TodoCommentActionName, comment_id: string | null): TodoCommentFailure => ({ ...info, action, comment_id, operation: forbiddenOperationOf(info) });

/**
 * ToDo のコメントのカスタムフック (AppAuthProvider の内側で使う)
 * @param {string} todo_id ToDo ID
 * @param {UseTodoCommentsOptions} options 投稿の権限・件数・変更の通知
 * @returns {TodoCommentsState} 一覧の状態と操作
*/
export const useTodoComments = (todo_id: string, { can_comment, limit, onChanged }: UseTodoCommentsOptions = {}): TodoCommentsState => {
    const client = useAppApiClient();
    const query: TodoCommentListQuery = limit !== undefined ? { limit } : {};
    const list = useCursorList<TodoCommentRead>({
        query_key: `app-todo-comments:${buildTodoCommentsUrl(todo_id, query)}`,
        fetchPage: (cursor) => fetchTodoCommentPage(client, todo_id, cursor === null ? query : { ...query, cursor }),
        classify: classifyAppError,
    });
    const { pending, failure, clearFailure, execute } = useActionRunner<TodoCommentActionName, TodoCommentFailure>({ classify: classifyAppError, toFailure, busyError });
    const { insertItem, replaceItem, removeItem } = list;

    const finish = useCallback((outcome: ActionOutcome<TodoCommentChange, TodoCommentFailure>): TodoCommentResult => {
        if (!outcome.ok) return outcome;
        const change = outcome.value;
        if (change.action === 'delete') removeItem(change.comment_id);
        else if (change.action === 'create') insertItem(change.comment, 'end');
        else replaceItem(change.comment);
        onChanged?.(change);
        return { ok: true, ...change };
    }, [insertItem, replaceItem, removeItem, onChanged]);

    const create = useCallback(async (body: string) => finish(await execute<TodoCommentChange>({
        action: 'create',
        target_id: null,
        precheck: () => commentCreateGuardOf(body, can_comment),
        run: async () => ({ action: 'create', comment: (await createTodoComment(client, todo_id, { body })).body }),
    })), [execute, finish, client, todo_id, can_comment]);

    const update = useCallback(async (comment: TodoCommentRead, body: string) => finish(await execute<TodoCommentChange>({
        action: 'update',
        target_id: comment.id,
        precheck: () => commentUpdateGuardOf(comment, body),
        run: async () => ({ action: 'update', comment: (await updateTodoComment(client, todo_id, comment.id, { body }, ifMatchOf(comment.version))).body }),
    })), [execute, finish, client, todo_id]);

    const remove = useCallback(async (comment: TodoCommentRead) => finish(await execute<TodoCommentChange>({
        action: 'delete',
        target_id: comment.id,
        precheck: () => commentRemoveGuardOf(comment),
        run: async () => {
            await deleteTodoComment(client, todo_id, comment.id, ifMatchOf(comment.version));
            return { action: 'delete', comment_id: comment.id };
        },
    })), [execute, finish, client, todo_id]);

    return { ...list, pending, failure, clearFailure, create, update, remove };
};

export default useTodoComments;
