// カンバン (AP-BRD) のドラッグ & ドロップの補助 (純粋関数と @dnd-kit に渡す設定)
// - 列 (useDroppable) の ID は boardColumnIdOf(status)、カード (useDraggable) の ID は ToDo ID、data は boardCardDataOf(todo)
// - キーボード: KeyboardSensor の coordinateGetter に boardKeyboardCoordinates を渡すと、左右の矢印キーで隣の列へ移る
//   (上下は列内の並べ替えになるため動かさない。AP-BRD-06)
// - 読み上げ: DndContext の accessibility に { announcements: todoBoardAnnouncementsOf(ラベル), screenReaderInstructions: TODO_BOARD_SCREEN_READER_INSTRUCTIONS }
// - ドロップ: onDragEnd で boardDropOf(event.active, event.over) を呼び、null でなければ useTodoBoard の moveCard(todo, to_status) を呼ぶ
// ステータスの表示名は画面 (pages/TodoCommon/todo_labels.ts) が持つため、引数で受け取る。
import { KeyboardCode, type Active, type ClientRect, type KeyboardCoordinateGetter, type Over, type UniqueIdentifier, type Announcements, type ScreenReaderInstructions } from '@dnd-kit/core';
import { TODO_STATUSES, type TodoRead, type TodoStatus } from '@/main_app/api/contract';

/** 列 (useDroppable) の ID の接頭辞 */
const COLUMN_ID_PREFIX = 'todo-board-column:';

/** カードの data の種別 (他の DnD の要素と区別する) */
const CARD_KIND = 'todo-board-card';

/** 移動後のカードを列の上端からどれだけ下に置くか (px。列の見出しを避ける) */
const COLUMN_TOP_OFFSET = 48;

/**
 * カード (useDraggable) の data。
 */
export type TodoBoardCardData = {
    kind: typeof CARD_KIND;
    todo: TodoRead;
};

/** 画面上の座標 (@dnd-kit の Coordinates と同じ形)。 */
export type BoardCoordinates = {
    x: number;
    y: number;
};

/**
 * 列の ID を作る関数
 * @param {TodoStatus} status ステータス
 * @returns {string} 列の ID
*/
export const boardColumnIdOf = (status: TodoStatus): string => `${COLUMN_ID_PREFIX}${status}`;

/**
 * 列の ID からステータスを取り出す関数
 * @param {UniqueIdentifier | null | undefined} id 列の ID
 * @returns {TodoStatus | null} ステータス (列の ID でなければ null)
*/
export const boardStatusOfColumnId = (id: UniqueIdentifier | null | undefined): TodoStatus | null => {
    if (typeof id !== 'string' || !id.startsWith(COLUMN_ID_PREFIX)) return null;
    const value = id.slice(COLUMN_ID_PREFIX.length);
    return TODO_STATUSES.find((status) => status === value) ?? null;
};

/**
 * カードの data を作る関数
 * @param {TodoRead} todo ToDo
 * @returns {TodoBoardCardData} data
*/
export const boardCardDataOf = (todo: TodoRead): TodoBoardCardData => ({ kind: CARD_KIND, todo });

/**
 * @dnd-kit の data からカードの ToDo を取り出す関数
 * @param {unknown} data active.data.current
 * @returns {TodoRead | null} ToDo (カードでなければ null)
*/
export const boardCardTodoOf = (data: unknown): TodoRead | null => {
    if (typeof data !== 'object' || data === null) return null;
    const card = data as Partial<TodoBoardCardData>;
    return card.kind === CARD_KIND && card.todo !== undefined ? card.todo : null;
};

/**
 * 隣の列のステータスを返す関数
 * @param {TodoStatus} status 今の列
 * @param {-1 | 1} direction -1 で左、1 で右
 * @returns {TodoStatus | null} 隣の列 (端なら null)
*/
export const adjacentBoardStatus = (status: TodoStatus, direction: -1 | 1): TodoStatus | null => TODO_STATUSES[TODO_STATUSES.indexOf(status) + direction] ?? null;

/**
 * 列の中にカードを置く座標を計算する関数 (列の横方向の中央、上端から少し下)
 * @param {ClientRect} column 移動先の列の矩形
 * @param {{ width: number }} card ドラッグ中のカードの大きさ
 * @returns {BoardCoordinates} カードの左上の座標
*/
export const boardCoordinatesInColumn = (column: Pick<ClientRect, 'left' | 'top' | 'width' | 'height'>, card: { width: number }): BoardCoordinates => ({
    x: column.left + Math.max(0, (column.width - card.width) / 2),
    y: column.top + Math.min(COLUMN_TOP_OFFSET, Math.max(0, column.height / 2)),
});

/**
 * キーボードの方向を返す関数
 * @param {string} code KeyboardEvent.code
 * @returns {-1 | 1 | null} -1 で左、1 で右 (左右以外は null)
*/
const directionOf = (code: string): -1 | 1 | null => {
    if (code === KeyboardCode.Left) return -1;
    if (code === KeyboardCode.Right) return 1;
    return null;
};

/**
 * キーボードで隣の列へ移すための coordinateGetter (KeyboardSensor の options に渡す)
 * 今の列は、カードが上にある列 (over)、無ければカードの元のステータス。上下の矢印キーでは動かさない。
*/
export const boardKeyboardCoordinates: KeyboardCoordinateGetter = (event, { context }) => {
    const direction = directionOf(event.code);
    if (direction === null) return undefined;
    const current = boardStatusOfColumnId(context.over?.id) ?? boardCardTodoOf(context.active?.data.current)?.status ?? null;
    const next = current === null ? null : adjacentBoardStatus(current, direction);
    if (next === null) return undefined;
    const column = context.droppableRects.get(boardColumnIdOf(next));
    if (column === undefined) return undefined;
    event.preventDefault();
    return boardCoordinatesInColumn(column, { width: context.collisionRect?.width ?? 0 });
};

/**
 * ドロップの結果から、移すカードと移動先のステータスを取り出す関数 (onDragEnd で使う)
 * @param {Pick<Active, 'data'>} active ドラッグしたもの
 * @param {Pick<Over, 'id'> | null} over ドロップした先
 * @returns {{ todo: TodoRead, to_status: TodoStatus } | null} 移動 (列の外・同じ列・カード以外は null)
*/
export const boardDropOf = (active: Pick<Active, 'data'>, over: Pick<Over, 'id'> | null): { todo: TodoRead; to_status: TodoStatus } | null => {
    const todo = boardCardTodoOf(active.data.current);
    const to_status = boardStatusOfColumnId(over?.id);
    if (todo === null || to_status === null || to_status === todo.status) return null;
    return { todo, to_status };
};

/** スクリーンリーダー向けの操作説明 (DndContext の accessibility.screenReaderInstructions)。 */
export const TODO_BOARD_SCREEN_READER_INSTRUCTIONS: ScreenReaderInstructions = {
    draggable: 'カードを移すには、スペースキーまたは Enter キーで持ち上げ、左右の矢印キーで隣の列へ動かし、もう一度スペースキーまたは Enter キーで置きます。Escape キーで取り消します。カードのメニューからもステータスを変えられます。',
};

/**
 * 読み上げの文言を作る関数 (DndContext の accessibility.announcements)
 * @param {Readonly<Record<TodoStatus, string>>} status_labels ステータスの表示名 (pages/TodoCommon/todo_labels.ts の TODO_STATUS_LABELS)
 * @returns {Announcements} 読み上げの文言
*/
export const todoBoardAnnouncementsOf = (status_labels: Readonly<Record<TodoStatus, string>>): Announcements => {
    const titleOf = (active: Pick<Active, 'data'>): string => boardCardTodoOf(active.data.current)?.title ?? 'カード';
    const fromOf = (active: Pick<Active, 'data'>): string => {
        const status = boardCardTodoOf(active.data.current)?.status;
        return status === undefined ? '' : status_labels[status];
    };
    const columnOf = (over: Pick<Over, 'id'> | null): string | null => {
        const status = boardStatusOfColumnId(over?.id);
        return status === null ? null : status_labels[status];
    };
    return {
        onDragStart: ({ active }) => `「${titleOf(active)}」を持ち上げました。今の列は「${fromOf(active)}」です。`,
        onDragOver: ({ active, over }) => {
            const column = columnOf(over);
            return column === null ? `「${titleOf(active)}」はどの列の上にもありません。` : `「${titleOf(active)}」を「${column}」の列の上に動かしました。`;
        },
        onDragEnd: ({ active, over }) => {
            const drop = boardDropOf(active, over);
            if (drop !== null) return `「${drop.todo.title}」を「${status_labels[drop.to_status]}」の列に置きました。ステータスを変更します。`;
            return `「${titleOf(active)}」は「${fromOf(active)}」の列のままです。`;
        },
        onDragCancel: ({ active }) => `移動を取り消しました。「${titleOf(active)}」は「${fromOf(active)}」の列のままです。`,
    };
};
