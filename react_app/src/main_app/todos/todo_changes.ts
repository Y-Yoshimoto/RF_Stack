// ToDo の変更内容の組み立てと、API を呼ぶ前の確認 (純粋関数)
// - 更新は「実際に値が変わる項目」だけを送り、その項目で権限を確かめる (サーバーの判定と同じ。ToDoApp.md §10 #7)
// - permissions は詳細 (TodoDetail) にだけある。一覧の要素 (TodoRead) から操作する場合は事前の確認をせず API に任せる
// useTodoActions が使う。画面は diffTodoChanges で「保存できる変更があるか」を判定できる。
import {
    ifMatchOf,
    TODO_LIMITS,
    type TodoCreate,
    type TodoDetail,
    type TodoOperation,
    type TodoPermissions,
    type TodoPriority,
    type TodoRead,
    type TodoStatus,
    type TodoUpdate,
    type TodoVisibility,
} from '@/main_app/api/contract';
import { AppGuardError, type AppErrorInfo } from '@/main_app/api/errors';

/**
 * 閲覧範囲と公開先組織 (同時に変える)。
 * `organization` 以外では organization_ids は送らず、公開先は空になる。`organization` では 1 つ以上必須 (AP-VIS-07)。
 */
export type TodoAudience = {
    visibility: TodoVisibility;
    organization_ids: readonly string[];
};

/**
 * ToDo の変更内容 (画面からの指定。項目単位で、指定した項目だけを扱う)。
 */
export type TodoChanges = {
    title?: string;
    /** 説明。null または空文字で消す。 */
    description?: string | null;
    /** 期限 (`YYYY-MM-DD`)。null で消す。 */
    due_date?: string | null;
    priority?: TodoPriority;
    status?: TodoStatus;
    /** 閲覧範囲と公開先組織。 */
    audience?: TodoAudience;
};

/**
 * 操作の対象 (ToDo ID・If-Match に付ける ETag・差分と権限の確認に使う現在の値)。
 * todoTargetOf で作る (useTodo の target、一覧の要素)。
 */
export type TodoTarget = {
    todo_id: string;
    /** 取得済みの ETag。null は未取得 (送信しない。フックが API を呼ばずに弾く)。 */
    etag: string | null;
    /** 現在の値。詳細なら permissions で事前に確認する。null なら差分を取らず指定どおり送り、権限は API に任せる。 */
    current: TodoRead | TodoDetail | null;
};

/**
 * ToDo の permissions で不可の操作として、API を呼ばずに弾いたことを表す例外 (kind: forbidden、code: todo_operation_forbidden)。
 */
export class TodoGuardError extends AppGuardError {
    /** 弾いた操作 (API の 403 の拡張メンバー operation と同じ値)。 */
    readonly operation: TodoOperation;

    constructor(operation: TodoOperation) {
        super('todo_operation_not_permitted');
        this.name = 'TodoGuardError';
        this.operation = operation;
    }
}

/** 操作と、必要な ToDo の権限 (null はコメントごとの permissions で判定する操作) */
const PERMISSION_OF: Record<TodoOperation, keyof TodoPermissions | null> = {
    edit_fields: 'can_edit_fields',
    change_status: 'can_change_status',
    change_visibility: 'can_change_visibility',
    change_assignees: 'can_change_assignees',
    delete: 'can_delete',
    edit_comment: null,
    delete_comment: null,
    edit_checklist: 'can_edit_checklist',
    check_checklist_item: 'can_check_checklist',
};

const TODO_OPERATIONS = Object.keys(PERMISSION_OF) as TodoOperation[];

/**
 * 詳細 (permissions を持つ) かを判定する関数
 * @param {TodoRead | TodoDetail} todo ToDo
 * @returns {boolean} 詳細なら true
*/
export const isTodoDetail = (todo: TodoRead | TodoDetail): todo is TodoDetail => 'permissions' in todo;

/**
 * 操作の対象を作る関数
 * @param {TodoRead | TodoDetail} todo 現在の値 (useTodo の todo、または一覧の要素)
 * @param {string | null} etag 保持している ETag (省略時は version から作る。useTodo では etag を渡す)
 * @returns {TodoTarget} 対象
*/
export const todoTargetOf = (todo: TodoRead | TodoDetail, etag?: string | null): TodoTarget => ({
    todo_id: todo.id,
    etag: etag === undefined ? ifMatchOf(todo.version) : etag,
    current: todo,
});

/**
 * 対象の permissions を返す関数
 * @param {TodoTarget} target 対象
 * @returns {TodoPermissions | null} permissions (一覧の要素など、分からなければ null)
*/
export const permissionsOfTarget = (target: TodoTarget): TodoPermissions | null => (target.current !== null && isTodoDetail(target.current) ? target.current.permissions : null);

/**
 * 詳細を一覧の要素の形にする関数 (説明・permissions を除く。一覧の replaceItem に使う)
 * @param {TodoDetail} detail 詳細
 * @returns {TodoRead} 一覧の要素
*/
export const todoReadOf = (detail: TodoDetail): TodoRead => {
    const { id, title, status, priority, due_date, visibility, effective_visibility, organizations, assignees, created_by, updated_by, creator, updater, checklist, comment_count, version, created_at, updated_at } = detail;
    return { id, title, status, priority, due_date, visibility, effective_visibility, organizations, assignees, created_by, updated_by, creator, updater, checklist, comment_count, version, created_at, updated_at };
};

/**
 * 公開先組織の再指定を促すべきかを判定する関数 (organization で有効な公開先が無くなった。AP-VIS-08)
 * @param {TodoRead} todo ToDo
 * @returns {boolean} 促すべきなら true
*/
export const needsOrganizationReselect = (todo: TodoRead): boolean => todo.visibility === 'organization' && todo.effective_visibility !== 'organization';

/**
 * ID の集合が等しいかを判定する関数 (順序・重複は問わない)
 * @param {readonly string[]} a 集合
 * @param {readonly string[]} b 集合
 * @returns {boolean} 等しければ true
*/
export const sameIdSet = (a: readonly string[], b: readonly string[]): boolean => {
    const left = new Set(a);
    const right = new Set(b);
    return left.size === right.size && [...left].every((id) => right.has(id));
};

/** 説明の空文字は null と同じ (サーバーも空文字を null として扱う) */
const normalizeDescription = (value: string | null | undefined): string | null => (value === undefined || value === null || value === '' ? null : value);

/**
 * 閲覧範囲の指定が現在と同じかを判定する関数
 * @param {TodoRead} current 現在の値
 * @param {TodoAudience} audience 指定
 * @returns {boolean} 同じなら true
*/
const sameAudience = (current: TodoRead, audience: TodoAudience): boolean => {
    if (current.visibility !== audience.visibility) return false;
    if (audience.visibility !== 'organization') return true;
    return sameIdSet(current.organizations.map((organization) => organization.id), audience.organization_ids);
};

/**
 * 変更内容のうち、現在の値から実際に変わる項目だけを残す関数
 * 現在の値が無い (null) 場合は指定どおり返す。一覧の要素は説明を持たないため、説明は常に残す。
 * @param {TodoRead | TodoDetail | null} current 現在の値
 * @param {TodoChanges} changes 変更内容
 * @returns {TodoChanges} 実際に変わる項目
*/
export const diffTodoChanges = (current: TodoRead | TodoDetail | null, changes: TodoChanges): TodoChanges => {
    if (current === null) return changes;
    const description_changed = changes.description !== undefined && (!isTodoDetail(current) || normalizeDescription(current.description) !== normalizeDescription(changes.description));
    return {
        ...(changes.title !== undefined && changes.title !== current.title ? { title: changes.title } : {}),
        ...(description_changed ? { description: changes.description } : {}),
        ...(changes.due_date !== undefined && changes.due_date !== current.due_date ? { due_date: changes.due_date } : {}),
        ...(changes.priority !== undefined && changes.priority !== current.priority ? { priority: changes.priority } : {}),
        ...(changes.status !== undefined && changes.status !== current.status ? { status: changes.status } : {}),
        ...(changes.audience !== undefined && !sameAudience(current, changes.audience) ? { audience: changes.audience } : {}),
    };
};

/**
 * 変更内容を PATCH の本文にする関数 (指定した項目だけを入れる)
 * @param {TodoChanges} changes 変更内容
 * @returns {TodoUpdate} 本文
*/
export const toTodoUpdate = (changes: TodoChanges): TodoUpdate => {
    const audience = changes.audience;
    return {
        ...(changes.title !== undefined ? { title: changes.title } : {}),
        ...(changes.description !== undefined ? { description: normalizeDescription(changes.description) } : {}),
        ...(changes.due_date !== undefined ? { due_date: changes.due_date } : {}),
        ...(changes.priority !== undefined ? { priority: changes.priority } : {}),
        ...(changes.status !== undefined ? { status: changes.status } : {}),
        ...(audience !== undefined ? { visibility: audience.visibility } : {}),
        ...(audience?.visibility === 'organization' ? { organization_ids: [...new Set(audience.organization_ids)] } : {}),
    };
};

/**
 * 変更内容に必要な操作を返す関数 (サーバーと同じ順: 項目 → ステータス → 閲覧範囲)
 * @param {TodoChanges} changes 変更内容 (diffTodoChanges の結果)
 * @returns {TodoOperation[]} 必要な操作
*/
export const requiredTodoOperationsOf = (changes: TodoChanges): TodoOperation[] => {
    const edits_fields = changes.title !== undefined || changes.description !== undefined || changes.due_date !== undefined || changes.priority !== undefined;
    return [
        ...(edits_fields ? (['edit_fields'] as const) : []),
        ...(changes.status !== undefined ? (['change_status'] as const) : []),
        ...(changes.audience !== undefined ? (['change_visibility'] as const) : []),
    ];
};

/**
 * permissions で不可の操作を返す関数
 * @param {TodoPermissions | null} permissions 権限 (null なら確かめない)
 * @param {readonly TodoOperation[]} operations 必要な操作
 * @returns {TodoOperation | null} 最初の不可の操作 (無ければ null)
*/
export const deniedTodoOperationOf = (permissions: TodoPermissions | null, operations: readonly TodoOperation[]): TodoOperation | null => {
    if (permissions === null) return null;
    return operations.find((operation) => {
        const permission = PERMISSION_OF[operation];
        return permission !== null && !permissions[permission];
    }) ?? null;
};

/**
 * 閲覧範囲の指定が organization で公開先組織が無いかを判定する関数
 * @param {TodoVisibility | undefined} visibility 閲覧範囲
 * @param {readonly string[] | undefined} organization_ids 公開先組織
 * @returns {boolean} 公開先組織が足りなければ true
*/
const lacksOrganizations = (visibility: TodoVisibility | undefined, organization_ids: readonly string[] | undefined): boolean => visibility === 'organization' && (organization_ids ?? []).length === 0;

/**
 * 作成の前に弾く理由を返す関数
 * @param {TodoCreate} input 入力
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const createGuardOf = (input: TodoCreate): AppGuardError | null => {
    if (lacksOrganizations(input.visibility, input.organization_ids)) return new AppGuardError('todo_organizations_required');
    if (new Set(input.assignee_ids ?? []).size > TODO_LIMITS.ASSIGNEES_MAX) return new AppGuardError('todo_too_many_assignees');
    return null;
};

/**
 * 作成の入力を整える関数 (ID の重複を除き、organization 以外では公開先組織を送らない)
 * @param {TodoCreate} input 入力
 * @returns {TodoCreate} 本文
*/
export const toTodoCreate = (input: TodoCreate): TodoCreate => {
    const { organization_ids, assignee_ids, ...rest } = input;
    return {
        ...rest,
        ...(input.visibility === 'organization' && organization_ids !== undefined ? { organization_ids: [...new Set(organization_ids)] } : {}),
        ...(assignee_ids !== undefined ? { assignee_ids: [...new Set(assignee_ids)] } : {}),
    };
};

/**
 * 更新の前に弾く理由を返す関数 (変更なし → 権限 → 公開先組織 → ETag の順)
 * @param {TodoTarget} target 対象
 * @param {TodoChanges} changes 実際に変わる項目 (diffTodoChanges の結果)
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const updateGuardOf = (target: TodoTarget, changes: TodoChanges): AppGuardError | null => {
    if (Object.keys(toTodoUpdate(changes)).length === 0) return new AppGuardError('empty_changes');
    const denied = deniedTodoOperationOf(permissionsOfTarget(target), requiredTodoOperationsOf(changes));
    if (denied !== null) return new TodoGuardError(denied);
    if (lacksOrganizations(changes.audience?.visibility, changes.audience?.organization_ids)) return new AppGuardError('todo_organizations_required');
    if (!target.etag) return new AppGuardError('missing_etag');
    return null;
};

/**
 * 担当者の置き換えの前に弾く理由を返す関数 (上限 → 変更なし → 権限 → ETag の順)
 * @param {TodoTarget} target 対象
 * @param {readonly string[]} user_ids 担当者にするユーザー ID の全件
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const assigneesGuardOf = (target: TodoTarget, user_ids: readonly string[]): AppGuardError | null => {
    if (new Set(user_ids).size > TODO_LIMITS.ASSIGNEES_MAX) return new AppGuardError('todo_too_many_assignees');
    if (target.current !== null && sameIdSet(target.current.assignees.map((assignee) => assignee.user_id), user_ids)) return new AppGuardError('empty_changes');
    if (deniedTodoOperationOf(permissionsOfTarget(target), ['change_assignees']) !== null) return new TodoGuardError('change_assignees');
    if (!target.etag) return new AppGuardError('missing_etag');
    return null;
};

/**
 * 削除の前に弾く理由を返す関数 (権限 → ETag の順)
 * @param {TodoTarget} target 対象
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const removeGuardOf = (target: TodoTarget): AppGuardError | null => {
    if (deniedTodoOperationOf(permissionsOfTarget(target), ['delete']) !== null) return new TodoGuardError('delete');
    if (!target.etag) return new AppGuardError('missing_etag');
    return null;
};

/**
 * 失敗から、拒否された操作を取り出す関数 (API の 403 の拡張メンバー operation、または API を呼ばずに弾いた操作)
 * @param {AppErrorInfo} info 分類したエラー
 * @returns {TodoOperation | null} 操作 (無ければ null)
*/
export const forbiddenOperationOf = (info: AppErrorInfo): TodoOperation | null => {
    if (info.error instanceof TodoGuardError) return info.error.operation;
    const operation = info.problem?.operation;
    return TODO_OPERATIONS.find((value) => value === operation) ?? null;
};
