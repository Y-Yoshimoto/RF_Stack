/**
 * @description:
 * ToDo のチェックリスト (AP-CHK) の取得と変更のカスタムフック
 * - 取得はチェックリスト全体と ETag (チェックリストの版)。todo_id が変わるか reload を呼ぶと取り直す。閲覧できない ToDo は 404 todo_not_found
 * - 変更 (add / rename / toggle / remove / reorder) の応答はすべてチェックリスト全体と新しい ETag で、取り直さずに置き換える
 * - If-Match: rename / toggle / remove は項目の版 (item.version)、reorder はチェックリストの ETag。add は不要 (§10 #17)
 * - 権限で不可の操作は API を呼ばずに失敗にする (kind: forbidden、operation: edit_checklist / check_checklist_item)。
 *   項目名の空・200 文字超え、項目数の上限 (100)、並べ替えの集合の不一致、変更なしも API を呼ばない
 * - API の失敗が requires_reload (412 todo_checklist_version_conflict、404 todo_checklist_item_not_found、403、422 mismatch) のときは、
 *   表示を保ったまま最新を取り直す (refresh)。結果の refreshed / failure_refreshed が true なら「最新を表示しました」と知らせる
 * - チェックリストの変更は ToDo 本体の ETag を変えない (useTodo の取り直しは不要。進捗を表示し直す場合は onChanged を使う)
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
*/
import { useCallback, useState } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import { ifMatchOf, type TodoChecklistItemRead, type TodoChecklistPermissions, type TodoChecklistRead, type TodoOperation } from '@/main_app/api/contract';
import { AppGuardError, classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { addTodoChecklistItem, deleteTodoChecklistItem, fetchTodoChecklist, reorderTodoChecklist, updateTodoChecklistItem } from '@/main_app/api/todo_checklist';
import type { WithEtag } from '@/shared/api/etag';
import { useActionRunner, type ActionOutcome } from '@/shared/hooks/useActionRunner';
import { useVersionedResource } from '@/shared/hooks/useVersionedResource';
import {
    checklistAddGuardOf,
    checklistRemoveGuardOf,
    checklistRenameGuardOf,
    checklistReorderGuardOf,
    checklistToggleGuardOf,
    isChecklistOrderMismatch,
    normalizeChecklistTitle,
} from './checklist_changes';
import { forbiddenOperationOf } from './todo_changes';

/** チェックリストの操作の種類。 */
export type TodoChecklistActionName = 'add' | 'rename' | 'toggle' | 'remove' | 'reorder';

/**
 * チェックリストの操作の失敗。
 */
export type TodoChecklistFailure = AppErrorInfo & {
    action: TodoChecklistActionName;
    /** 対象の項目 ID (追加・並べ替えでは null)。 */
    item_id: string | null;
    /** 権限が無く拒否された操作 (edit_checklist / check_checklist_item。それ以外は null)。 */
    operation: TodoOperation | null;
};

/**
 * チェックリストの操作の結果。
 * 失敗の refreshed は、この失敗の後に最新を取り直して表示したこと (未保存の入力は画面側で残す)。
 */
export type TodoChecklistResult =
    | { ok: true; action: TodoChecklistActionName; checklist: TodoChecklistRead; etag: string }
    | { ok: false; failure: TodoChecklistFailure; refreshed: boolean };

export type UseTodoChecklistOptions = {
    /** requires_reload の失敗の後に自動で取り直すか (省略時は true)。 */
    auto_refresh?: boolean;
    /** 変更に成功したときに呼ばれる (一覧・詳細の進捗の表示し直しなど)。 */
    onChanged?: (checklist: TodoChecklistRead) => void;
};

/**
 * チェックリストの状態と操作。
 */
export type TodoChecklistState = {
    status: 'loading' | 'success' | 'error';
    /** チェックリスト (取得前・失敗時は null)。変更の応答を反映したもの。 */
    checklist: TodoChecklistRead | null;
    /** チェックリストの ETag (並べ替えの If-Match)。 */
    etag: string | null;
    /** 操作者の権限 (取得前・失敗時は null)。 */
    permissions: TodoChecklistPermissions | null;
    /** 取得の失敗 (status === 'error' のとき)。 */
    error: AppErrorInfo | null;
    /** 取り直す (取得中は loading)。 */
    reload: () => void;
    /** 表示を保ったまま取り直す。 */
    refresh: () => Promise<boolean>;
    is_refreshing: boolean;
    /** 実行中の操作 (無ければ null)。 */
    pending: TodoChecklistActionName | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: TodoChecklistFailure | null;
    /** 最後の失敗の後に最新を取り直して表示した (「他の人が変更したため最新を表示しました」の表示に使う)。 */
    failure_refreshed: boolean;
    clearFailure: () => void;
    /** 項目を追加する (項目名は前後の空白を除いて送る。position の省略時は末尾)。 */
    add: (title: string, position?: number) => Promise<TodoChecklistResult>;
    /** 項目名を変える。 */
    rename: (item: TodoChecklistItemRead, title: string) => Promise<TodoChecklistResult>;
    /** 完了・未完了を切り替える (is_done の省略時は反転)。 */
    toggle: (item: TodoChecklistItemRead, is_done?: boolean) => Promise<TodoChecklistResult>;
    /** 項目を削除する。 */
    remove: (item: TodoChecklistItemRead) => Promise<TodoChecklistResult>;
    /** 並べ替える (全項目の ID の新しい並び。checklist_changes.ts の moveChecklistItemIds / shiftChecklistItemIds で作る)。 */
    reorder: (item_ids: readonly string[]) => Promise<TodoChecklistResult>;
};

/** 変更の成功 (応答のチェックリスト全体と ETag) */
type ChecklistChange = { action: TodoChecklistActionName; value: WithEtag<TodoChecklistRead> };

/**
 * 変更の応答を重ねる関数 (応答は全体なので置き換える。チェックリストの版が古い応答は使わない)
 * @param {WithEtag<TodoChecklistRead>} current 現在の値
 * @param {WithEtag<TodoChecklistRead>} update 変更の応答
 * @returns {WithEtag<TodoChecklistRead>} 反映後の値
*/
export const mergeChecklistUpdate = (current: WithEtag<TodoChecklistRead>, update: WithEtag<TodoChecklistRead>): WithEtag<TodoChecklistRead> => {
    if (update.body.todo_id !== current.body.todo_id || update.body.version < current.body.version) return current;
    return update;
};

const busyError = () => new AppGuardError('action_in_progress');
const toFailure = (info: AppErrorInfo, action: TodoChecklistActionName, item_id: string | null): TodoChecklistFailure => ({
    ...info,
    requires_reload: info.requires_reload || isChecklistOrderMismatch(info),
    action,
    item_id,
    operation: forbiddenOperationOf(info),
});

/** 取得前に操作したときの理由 (取り直してからやり直す) */
const notLoaded = () => new AppGuardError('missing_etag');

/**
 * ToDo のチェックリストのカスタムフック (AppAuthProvider の内側で使う)
 * @param {string} todo_id ToDo ID
 * @param {UseTodoChecklistOptions} options 自動の取り直し・変更の通知
 * @returns {TodoChecklistState} チェックリストの状態と操作
*/
export const useTodoChecklist = (todo_id: string, { auto_refresh = true, onChanged }: UseTodoChecklistOptions = {}): TodoChecklistState => {
    const client = useAppApiClient();
    const resource = useVersionedResource<TodoChecklistRead, WithEtag<TodoChecklistRead>>({
        key: `app-todo-checklist:${todo_id}`,
        load: () => fetchTodoChecklist(client, todo_id),
        merge: mergeChecklistUpdate,
        classify: classifyAppError,
    });
    const { value: checklist, etag, applyUpdate, refresh } = resource;
    const { pending, failure, clearFailure, execute } = useActionRunner<TodoChecklistActionName, TodoChecklistFailure>({ classify: classifyAppError, toFailure, busyError });
    const [refreshed_failure, setRefreshedFailure] = useState<TodoChecklistFailure | null>(null);

    const finish = useCallback(async (outcome: ActionOutcome<ChecklistChange, TodoChecklistFailure>): Promise<TodoChecklistResult> => {
        if (outcome.ok) {
            const { action, value } = outcome.value;
            applyUpdate(value);
            onChanged?.(value.body);
            return { ok: true, action, checklist: value.body, etag: value.etag };
        }
        const should_refresh = auto_refresh && outcome.failure.status !== null && outcome.failure.requires_reload;
        const refreshed = should_refresh ? await refresh() : false;
        if (refreshed) setRefreshedFailure(outcome.failure);
        return { ok: false, failure: outcome.failure, refreshed };
    }, [applyUpdate, onChanged, auto_refresh, refresh]);

    /**
     * 操作を実行する関数 (取得前は API を呼ばずに弾く)
     * @param {TodoChecklistActionName} action 操作
     * @param {string | null} item_id 対象の項目
     * @param {(current: TodoChecklistRead) => AppGuardError | null} guard 実行前の確認
     * @param {() => Promise<WithEtag<TodoChecklistRead>>} call API 呼び出し
     * @returns {Promise<TodoChecklistResult>} 結果
    */
    const run = useCallback(async (
        action: TodoChecklistActionName,
        item_id: string | null,
        guard: (current: TodoChecklistRead) => AppGuardError | null,
        call: () => Promise<WithEtag<TodoChecklistRead>>,
    ) => finish(await execute<ChecklistChange>({
        action,
        target_id: item_id,
        precheck: () => (checklist === null ? notLoaded() : guard(checklist)),
        run: async () => ({ action, value: await call() }),
    })), [execute, finish, checklist]);

    const add = useCallback((title: string, position?: number) => run(
        'add', null,
        (current) => checklistAddGuardOf(current, title),
        () => addTodoChecklistItem(client, todo_id, { title: normalizeChecklistTitle(title), ...(position !== undefined ? { position } : {}) }),
    ), [run, client, todo_id]);

    const rename = useCallback((item: TodoChecklistItemRead, title: string) => run(
        'rename', item.id,
        (current) => checklistRenameGuardOf(current, item, title),
        () => updateTodoChecklistItem(client, todo_id, item.id, { title: normalizeChecklistTitle(title) }, ifMatchOf(item.version)),
    ), [run, client, todo_id]);

    const toggle = useCallback((item: TodoChecklistItemRead, is_done: boolean = !item.is_done) => run(
        'toggle', item.id,
        (current) => checklistToggleGuardOf(current, item, is_done),
        () => updateTodoChecklistItem(client, todo_id, item.id, { is_done }, ifMatchOf(item.version)),
    ), [run, client, todo_id]);

    const remove = useCallback((item: TodoChecklistItemRead) => run(
        'remove', item.id,
        (current) => checklistRemoveGuardOf(current),
        () => deleteTodoChecklistItem(client, todo_id, item.id, ifMatchOf(item.version)),
    ), [run, client, todo_id]);

    const reorder = useCallback((item_ids: readonly string[]) => run(
        'reorder', null,
        (current) => checklistReorderGuardOf(current, item_ids, etag),
        () => reorderTodoChecklist(client, todo_id, item_ids, etag ?? ''),
    ), [run, client, todo_id, etag]);

    return {
        status: resource.status,
        checklist,
        etag,
        permissions: checklist?.permissions ?? null,
        error: resource.error,
        reload: resource.reload,
        refresh,
        is_refreshing: resource.is_refreshing,
        pending,
        failure,
        failure_refreshed: failure !== null && failure === refreshed_failure,
        clearFailure,
        add,
        rename,
        toggle,
        remove,
        reorder,
    };
};

export default useTodoChecklist;
