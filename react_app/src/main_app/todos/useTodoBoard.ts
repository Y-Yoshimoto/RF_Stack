/**
 * @description:
 * ToDo のカンバン (ボード表示。AP-BRD) のカスタムフック
 * - ステータスごとの 3 列を、それぞれ useTodoList (先頭ページで include_total) で取得する。列ごとに総件数と続きの読み込みを持つ (AP-BRD-05)
 * - 表示範囲・絞り込み・並び順は一覧と共通で、ステータスの絞り込みだけは使わない (列がステータス。AP-BRD-02)
 * - moveCard は楽観的にカードを移し (移動先の列の先頭に置く)、useTodoActions の changeStatus (PATCH status) を呼ぶ。
 *   成功したら応答で置き換え、失敗したら元の列の元の位置に戻して failure を返す。
 *   412 / 403 / 404 (表示が古い) のときは該当の 2 列を取り直す
 * - 一覧の要素は permissions を持たないため、権限は API に任せる (掴めるかどうかは画面が list_rules の canChangeStatusInList で出し分ける)
*/
import { useCallback, useRef, useState } from 'react';
import type { TodoDetail, TodoRead, TodoStatus } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { todoReadOf, todoTargetOf } from './todo_changes';
import type { TodoActionUpdate } from './useTodo';
import { useTodoActions, type TodoActionFailure, type TodoActionResult } from './useTodoActions';
import { useTodoList, type TodoListState } from './useTodoList';

/**
 * ボードの列 (ステータス → 一覧の状態)。
 */
export type TodoBoardColumns = Readonly<Record<TodoStatus, TodoListState>>;

/**
 * カードの移動の結果。
 * - ok で todo が null: 同じ列への移動 (何もしていない)
 */
export type TodoBoardMoveResult = { ok: true; todo: TodoDetail | null } | { ok: false; failure: TodoActionFailure };

/**
 * ボードの状態と操作。
 */
export type TodoBoardState = {
    columns: TodoBoardColumns;
    /** 移動中のカードの ToDo ID (無ければ null)。 */
    moving_id: string | null;
    /** 最後の移動の失敗 (次の移動・clearFailure で消える)。 */
    failure: TodoActionFailure | null;
    clearFailure: () => void;
    /** カードを別の列へ移す (楽観的に移し、失敗したら戻す)。移動中に呼ぶと API を呼ばずに失敗 (kind: busy) にする。 */
    moveCard: (todo: TodoRead, to_status: TodoStatus) => Promise<TodoBoardMoveResult>;
    /** すべての列を先頭ページから取り直す。 */
    reload: () => void;
};

export type UseTodoBoardOptions = {
    /** ステータスの変更に成功したときに呼ばれる (詳細・要約の取り直しなどにつなぐ)。 */
    onUpdated?: (update: TodoActionUpdate) => void;
};

/**
 * 列の絞り込みを作る関数 (ステータスだけを列のものにする)
 * @param {TodoListFilter} filter 一覧と共通の絞り込み
 * @param {TodoStatus} status 列のステータス
 * @returns {TodoListFilter} 列の絞り込み
*/
export const boardColumnFilterOf = (filter: TodoListFilter, status: TodoStatus): TodoListFilter => ({ ...filter, status: [status] });

/**
 * 移動の失敗のうち、表示が古いため列を取り直すべきかを判定する関数 (API が返した 412 / 403 / 404)
 * @param {TodoActionFailure} failure 失敗
 * @returns {boolean} 取り直すべきなら true
*/
export const shouldReloadBoardColumns = (failure: TodoActionFailure): boolean => failure.status === 412 || failure.status === 403 || failure.status === 404;

/**
 * 変更操作の結果を移動の結果にする関数
 * @param {TodoActionResult} result 変更操作の結果
 * @returns {TodoBoardMoveResult} 移動の結果
*/
const moveResultOf = (result: TodoActionResult): TodoBoardMoveResult => {
    if (!result.ok) return result;
    return { ok: true, todo: result.action === 'delete' ? null : result.todo };
};

/**
 * ToDo のカンバンのカスタムフック (AppAuthProvider の内側で使う)
 * @param {TodoListFilter} filter 表示範囲・絞り込み・並び順・件数 (status は無視する)
 * @param {UseTodoBoardOptions} options 成功時の通知
 * @returns {TodoBoardState} ボードの状態と操作
*/
export const useTodoBoard = (filter: TodoListFilter = {}, { onUpdated }: UseTodoBoardOptions = {}): TodoBoardState => {
    const open = useTodoList(boardColumnFilterOf(filter, 'open'));
    const in_progress = useTodoList(boardColumnFilterOf(filter, 'in_progress'));
    const done = useTodoList(boardColumnFilterOf(filter, 'done'));
    const columns: TodoBoardColumns = { open, in_progress, done };
    const { failure, clearFailure, changeStatus } = useTodoActions({ onUpdated });
    const [moving_id, setMovingId] = useState<string | null>(null);
    // 移動中の二重の楽観的な移動を防ぐ (イベントハンドラーからのみ読み書きする)
    const is_moving = useRef(false);

    const moveCard = useCallback(async (todo: TodoRead, to_status: TodoStatus): Promise<TodoBoardMoveResult> => {
        const target = todoTargetOf(todo);
        // 移動中は changeStatus が API を呼ばずに busy で失敗する (カードは動かさない)
        if (is_moving.current) return moveResultOf(await changeStatus(target, to_status));
        if (todo.status === to_status) return { ok: true, todo: null };
        const from = columns[todo.status];
        const to = columns[to_status];
        const index = from.items.findIndex((item) => item.id === todo.id);
        from.removeItem(todo.id);
        to.insertItem({ ...todo, status: to_status }, 'start');
        is_moving.current = true;
        setMovingId(todo.id);
        const result = await changeStatus(target, to_status);
        is_moving.current = false;
        setMovingId(null);
        if (result.ok) {
            if (result.action !== 'delete') to.replaceItem(todoReadOf(result.todo));
            return moveResultOf(result);
        }
        to.removeItem(todo.id);
        from.insertItem(todo, index < 0 ? 'start' : index);
        if (shouldReloadBoardColumns(result.failure)) {
            from.reload();
            to.reload();
        }
        return result;
    }, [columns, changeStatus]);

    const reload = useCallback(() => {
        open.reload();
        in_progress.reload();
        done.reload();
    }, [open.reload, in_progress.reload, done.reload]);

    return { columns, moving_id, failure, clearFailure, moveCard, reload };
};

export default useTodoBoard;
