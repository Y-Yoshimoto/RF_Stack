// ToDo 一覧の行の操作可否のテスト
import { describe, expect, it } from 'vitest';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { assigneeOf, todoOf } from '@/main_app/testing/todo_test_data';
import { THIRD_USER_ID } from '@/main_app/testing/story_data';
import { canChangeStatusInList, hasListConditions } from './list_rules';

describe('canChangeStatusInList', () => {
    const others_todo = todoOf({ created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: THIRD_USER_ID })] });

    it('tenant_admin は、他人の ToDo でも変えられる', () => {
        expect(canChangeStatusInList(others_todo, SELF_USER_ID, true)).toBe(true);
    });

    it('作成者は変えられる', () => {
        expect(canChangeStatusInList(todoOf({ created_by: SELF_USER_ID, assignees: [] }), SELF_USER_ID, false)).toBe(true);
    });

    it('担当者は変えられる', () => {
        expect(canChangeStatusInList(todoOf({ created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: SELF_USER_ID })] }), SELF_USER_ID, false)).toBe(true);
    });

    it('作成者でも担当者でもない member は変えられない', () => {
        expect(canChangeStatusInList(others_todo, SELF_USER_ID, false)).toBe(false);
    });

    it('自分の ID が分からない間は、tenant_admin 以外は変えられない', () => {
        expect(canChangeStatusInList(todoOf({ created_by: SELF_USER_ID }), null, false)).toBe(false);
        expect(canChangeStatusInList(todoOf({ created_by: SELF_USER_ID }), null, true)).toBe(true);
    });
});

describe('hasListConditions', () => {
    it('表示範囲と並び順だけなら、絞り込みなしとする', () => {
        expect(hasListConditions({})).toBe(false);
        expect(hasListConditions({ scope: 'mine', sort: 'due_date' })).toBe(false);
    });

    it('それ以外の指定があれば、絞り込みありとする', () => {
        expect(hasListConditions({ q: 'a' })).toBe(true);
        expect(hasListConditions({ status: ['open'] })).toBe(true);
    });
});
