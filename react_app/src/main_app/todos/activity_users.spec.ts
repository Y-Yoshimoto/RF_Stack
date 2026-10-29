// activity_users.ts のテスト (応答の users によるユーザー名の解決)
import { describe, expect, it } from 'vitest';
import type { TodoActivityUsers } from '@/main_app/api/contract';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { activityOf } from '@/main_app/testing/todo_test_data';
import {
    mergeTodoActivityUsers,
    todoActivityActorOf,
    todoActivityAssigneeDeltaOf,
    todoActivityCreatedAssigneesOf,
    todoActivityUserNameLookupOf,
    todoActivityUserOf,
    withPageUsers,
} from './activity_users';

const UNKNOWN_ID = '01900000-0000-7000-8000-00000000a999';
const USERS: TodoActivityUsers = {
    [SELF_USER_ID]: { display_name: 'Hanako Suzuki', is_active: true },
    [OTHER_USER_ID]: { display_name: 'Taro Yamada', is_active: false },
};

describe('名前の解決', () => {
    it('users のキーにある ID は表示名と有効/無効を返し、無い ID は null (不明なユーザー)', () => {
        expect(todoActivityUserOf(USERS, OTHER_USER_ID)).toEqual({ display_name: 'Taro Yamada', is_active: false });
        expect(todoActivityUserOf(USERS, UNKNOWN_ID)).toBeNull();
        // プロトタイプのプロパティは引かない
        expect(todoActivityUserOf(USERS, 'toString')).toBeNull();
    });

    it('todoActivityUserNameLookupOf: 引けなければ「不明なユーザー」(文言は指定できる)', () => {
        expect(todoActivityUserNameLookupOf(USERS)(SELF_USER_ID)).toBe('Hanako Suzuki');
        expect(todoActivityUserNameLookupOf(USERS)(UNKNOWN_ID)).toBe('不明なユーザー');
        expect(todoActivityUserNameLookupOf(USERS, '(削除済み)')(UNKNOWN_ID)).toBe('(削除済み)');
    });

    it('assignees_changed の追加・削除を名前付きで返す (無効なユーザー・不明なユーザーを含む)', () => {
        const activity = activityOf({ action: 'assignees_changed', payload: { added: [OTHER_USER_ID, UNKNOWN_ID], removed: [SELF_USER_ID] } });
        expect(todoActivityAssigneeDeltaOf(activity, USERS)).toEqual({
            added: [{ user_id: OTHER_USER_ID, user: { display_name: 'Taro Yamada', is_active: false } }, { user_id: UNKNOWN_ID, user: null }],
            removed: [{ user_id: SELF_USER_ID, user: { display_name: 'Hanako Suzuki', is_active: true } }],
        });
        expect(todoActivityAssigneeDeltaOf(activityOf({ action: 'visibility_changed', payload: { organization_ids: { added: ['o1'], removed: [] } } }), USERS)).toEqual({ added: [], removed: [] });
    });

    it('created の values.assignee_ids を名前付きで返す (形が合わなければ空)', () => {
        expect(todoActivityCreatedAssigneesOf(activityOf({ action: 'created', payload: { values: { assignee_ids: [OTHER_USER_ID, 1] } } }), USERS)).toEqual([{ user_id: OTHER_USER_ID, user: { display_name: 'Taro Yamada', is_active: false } }]);
        expect(todoActivityCreatedAssigneesOf(activityOf({ action: 'created', payload: { values: {} } }), USERS)).toEqual([]);
    });

    it('操作者は users を優先し、無ければ actor_display_name、どちらも無ければ null', () => {
        expect(todoActivityActorOf(activityOf({ actor_id: OTHER_USER_ID, actor_display_name: 'Old Name' }), USERS)).toEqual({ user_id: OTHER_USER_ID, user: { display_name: 'Taro Yamada', is_active: false } });
        expect(todoActivityActorOf(activityOf({ actor_id: UNKNOWN_ID, actor_display_name: 'Someone' }), USERS)).toEqual({ user_id: UNKNOWN_ID, user: { display_name: 'Someone', is_active: true } });
        expect(todoActivityActorOf(activityOf({ actor_id: UNKNOWN_ID, actor_display_name: null }), USERS)).toEqual({ user_id: UNKNOWN_ID, user: null });
    });
});

describe('ページの users', () => {
    it('withPageUsers は同じページの要素に同じ users を付け、無ければ空として扱う', () => {
        const [a, b] = withPageUsers([activityOf({ id: 'a' }), activityOf({ id: 'b' })], USERS);
        expect(a.page_users).toBe(b.page_users);
        expect(withPageUsers([activityOf()], undefined)[0].page_users).toEqual({});
    });

    it('mergeTodoActivityUsers は全ページの users をまとめる (同じ ID は先に読み込んだページのもの)', () => {
        const first = withPageUsers([activityOf({ id: 'a' })], { [SELF_USER_ID]: { display_name: 'New', is_active: true } });
        const second = withPageUsers([activityOf({ id: 'b' }), activityOf({ id: 'c' })], { [SELF_USER_ID]: { display_name: 'Old', is_active: true }, [OTHER_USER_ID]: { display_name: 'Taro', is_active: false } });
        expect(mergeTodoActivityUsers([...first, ...second])).toEqual({
            [SELF_USER_ID]: { display_name: 'New', is_active: true },
            [OTHER_USER_ID]: { display_name: 'Taro', is_active: false },
        });
        expect(mergeTodoActivityUsers([])).toEqual({});
    });
});
