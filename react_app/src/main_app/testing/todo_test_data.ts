// テスト用: ToDo のテストデータ (アプリのコードからは import しない)
import type {
    TodoActivityPage,
    TodoActivityRead,
    TodoActivityUsers,
    TodoAssigneeRead,
    TodoChecklistItemRead,
    TodoChecklistRead,
    TodoCommentRead,
    TodoDetail,
    TodoPermissions,
    TodoRead,
    TodoSummary,
    TodoUserRef,
} from '@/main_app/api/contract';
import { ORGANIZATION_ID, OTHER_USER_ID, SELF_USER_ID } from './app_test_support';

/** テストで使う ToDo ID */
export const TODO_ID = '01900000-0000-7000-8000-00000000c001';

/** すべての操作ができる権限 (作成者・tenant_admin) */
export const ALL_TODO_PERMISSIONS: TodoPermissions = {
    can_edit_fields: true,
    can_change_status: true,
    can_change_visibility: true,
    can_change_assignees: true,
    can_delete: true,
    can_comment: true,
    can_edit_checklist: true,
    can_check_checklist: true,
};

/** 担当者の権限 (ステータスと担当者の変更のみ) */
export const ASSIGNEE_TODO_PERMISSIONS: TodoPermissions = {
    can_edit_fields: false,
    can_change_status: true,
    can_change_visibility: false,
    can_change_assignees: true,
    can_delete: false,
    can_comment: true,
    can_edit_checklist: false,
    can_check_checklist: true,
};

/** 閲覧だけの権限 (コメントの投稿のみ) */
export const VIEWER_TODO_PERMISSIONS: TodoPermissions = {
    can_edit_fields: false,
    can_change_status: false,
    can_change_visibility: false,
    can_change_assignees: false,
    can_delete: false,
    can_comment: true,
    can_edit_checklist: false,
    can_check_checklist: false,
};

/**
 * ToDo が参照するユーザーのテストデータを作る関数
 * @param {string} id ユーザー ID
 * @param {string} display_name 表示名
 * @returns {TodoUserRef} ユーザー
*/
export const todoUserRefOf = (id: string = SELF_USER_ID, display_name: string = 'Hanako Suzuki'): TodoUserRef => ({ id, display_name, is_active: true });

/**
 * 担当者のテストデータを作る関数
 * @param {Partial<TodoAssigneeRead>} overrides 上書きする項目
 * @returns {TodoAssigneeRead} 担当者
*/
export const assigneeOf = (overrides: Partial<TodoAssigneeRead> = {}): TodoAssigneeRead => ({
    user_id: OTHER_USER_ID,
    display_name: 'Taro Yamada',
    is_active: true,
    assigned_at: '2026-10-01T00:00:00Z',
    assigned_by: SELF_USER_ID,
    ...overrides,
});

/**
 * ToDo (一覧の要素) のテストデータを作る関数
 * @param {Partial<TodoRead>} overrides 上書きする項目
 * @returns {TodoRead} ToDo
*/
export const todoOf = (overrides: Partial<TodoRead> = {}): TodoRead => ({
    id: TODO_ID,
    title: '見積もりを作る',
    status: 'open',
    priority: 'medium',
    due_date: '2026-11-01',
    visibility: 'organization',
    effective_visibility: 'organization',
    organizations: [{ id: ORGANIZATION_ID, name: '営業部' }],
    assignees: [assigneeOf()],
    created_by: SELF_USER_ID,
    updated_by: SELF_USER_ID,
    creator: todoUserRefOf(),
    updater: todoUserRefOf(),
    checklist: { done_count: 0, total_count: 0 },
    comment_count: 0,
    version: 3,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
});

/**
 * ToDo の詳細のテストデータを作る関数
 * @param {Partial<TodoDetail>} overrides 上書きする項目
 * @returns {TodoDetail} 詳細
*/
export const todoDetailOf = (overrides: Partial<TodoDetail> = {}): TodoDetail => ({ ...todoOf(), description: '先方に送る', permissions: ALL_TODO_PERMISSIONS, ...overrides });

/**
 * アクティビティのテストデータを作る関数
 * @param {Partial<TodoActivityRead>} overrides 上書きする項目
 * @returns {TodoActivityRead} アクティビティ
*/
export const activityOf = (overrides: Partial<TodoActivityRead> = {}): TodoActivityRead => ({
    id: '01900000-0000-7000-8000-00000000d001',
    todo_id: TODO_ID,
    actor_id: SELF_USER_ID,
    actor_display_name: 'Hanako Suzuki',
    action: 'created',
    payload: {},
    created_at: '2026-10-01T00:00:00Z',
    ...overrides,
});

/**
 * アクティビティ一覧 API (`GET /api/v1/todos/{todo_id}/activities`) の応答の本文を作る関数
 * @param {TodoActivityRead[]} items アクティビティ
 * @param {TodoActivityUsers} users ページのアクティビティが参照するユーザー (ユーザー ID → 表示名・有効/無効)
 * @param {string | null} next_cursor 次のページのカーソル
 * @returns {TodoActivityPage} 本文
*/
export const activityPageOf = (items: TodoActivityRead[], users: TodoActivityUsers = {}, next_cursor: string | null = null): TodoActivityPage => ({ items, next_cursor, total: null, users });

/** テストで使うコメント ID */
export const COMMENT_ID = '01900000-0000-7000-8000-00000000e001';
/** テストで使うチェックリスト項目 ID */
export const CHECKLIST_ITEM_ID = '01900000-0000-7000-8000-00000000f001';
/** テストで使う 2 つ目のチェックリスト項目 ID */
export const SECOND_CHECKLIST_ITEM_ID = '01900000-0000-7000-8000-00000000f002';

/**
 * コメントのテストデータを作る関数 (自分の投稿。編集・削除できる)
 * @param {Partial<TodoCommentRead>} overrides 上書きする項目
 * @returns {TodoCommentRead} コメント
*/
export const commentOf = (overrides: Partial<TodoCommentRead> = {}): TodoCommentRead => ({
    id: COMMENT_ID,
    todo_id: TODO_ID,
    author: todoUserRefOf(),
    body: '確認しました',
    version: 1,
    created_at: '2026-10-02T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    edited_at: null,
    permissions: { can_edit: true, can_delete: true },
    ...overrides,
});

/**
 * チェックリスト項目のテストデータを作る関数
 * @param {Partial<TodoChecklistItemRead>} overrides 上書きする項目
 * @returns {TodoChecklistItemRead} 項目
*/
export const checklistItemOf = (overrides: Partial<TodoChecklistItemRead> = {}): TodoChecklistItemRead => ({
    id: CHECKLIST_ITEM_ID,
    title: '見積書の雛形を探す',
    position: 0,
    is_done: false,
    done_at: null,
    done_by: null,
    version: 1,
    created_at: '2026-10-02T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    ...overrides,
});

/**
 * チェックリストのテストデータを作る関数 (件数は項目から数える)
 * @param {TodoChecklistItemRead[]} items 項目
 * @param {Partial<TodoChecklistRead>} overrides 上書きする項目
 * @returns {TodoChecklistRead} チェックリスト
*/
export const checklistOf = (items: TodoChecklistItemRead[] = [checklistItemOf()], overrides: Partial<TodoChecklistRead> = {}): TodoChecklistRead => ({
    todo_id: TODO_ID,
    version: 1,
    items,
    done_count: items.filter((item) => item.is_done).length,
    total_count: items.length,
    permissions: { can_edit: true, can_check: true },
    ...overrides,
});

/**
 * ホームの要約のテストデータを作る関数
 * @param {Partial<TodoSummary>} overrides 上書きする項目
 * @returns {TodoSummary} 要約
*/
export const summaryOf = (overrides: Partial<TodoSummary> = {}): TodoSummary => ({
    today: '2026-10-29',
    due_soon_until: '2026-11-05',
    assigned: { open: 3, in_progress: 1, overdue: 1, due_soon: 2 },
    created: { open: 2, in_progress: 0, overdue: 0 },
    ...overrides,
});
