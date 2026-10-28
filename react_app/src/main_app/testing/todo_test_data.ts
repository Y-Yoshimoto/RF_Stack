// テスト用: ToDo のテストデータ (アプリのコードからは import しない)
import type { TodoActivityRead, TodoAssigneeRead, TodoDetail, TodoPermissions, TodoRead } from '@/main_app/api/contract';
import { ORGANIZATION_ID, OTHER_USER_ID, SELF_USER_ID } from './app_test_support';

/** テストで使う ToDo ID */
export const TODO_ID = '01900000-0000-7000-8000-00000000c001';

/** すべての操作ができる権限 (作成者・tenant_admin) */
export const ALL_TODO_PERMISSIONS: TodoPermissions = { can_edit_fields: true, can_change_status: true, can_change_visibility: true, can_change_assignees: true, can_delete: true };

/** 担当者の権限 (ステータスと担当者の変更のみ) */
export const ASSIGNEE_TODO_PERMISSIONS: TodoPermissions = { can_edit_fields: false, can_change_status: true, can_change_visibility: false, can_change_assignees: true, can_delete: false };

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
