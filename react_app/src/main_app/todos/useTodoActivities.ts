/**
 * @description:
 * ToDo のアクティビティ (変更履歴。新しい順) を取得するカスタムフック (カーソル方式の「さらに読み込む」)
 * todo_id が変わるか reload を呼ぶと先頭ページから取り直す。閲覧できない ToDo は 404 todo_not_found。
 * 変更操作の後は新しい行が先頭に増えるため、useTodoActions の onUpdated で reload を呼ぶこと。
 * payload の読み取りは activity_payload.ts、ユーザーの名前の解決は activity_users.ts。
 * 応答のページごとの users (操作者・payload が参照するユーザー) を、読み込み済みの全ページ分まとめて users に入れる
 * (担当者の名前を引くためにユーザー一覧を全件取得する必要は無い)。
*/
import { useMemo } from 'react';
import { useAppApiClient } from '@/main_app/api/client';
import type { TodoActivityListQuery, TodoActivityUsers } from '@/main_app/api/contract';
import { classifyAppError } from '@/main_app/api/errors';
import { buildTodoActivitiesUrl, fetchTodoActivityPage } from '@/main_app/api/todos';
import { useCursorList, type CursorListState } from '@/shared/hooks/useCursorList';
import { mergeTodoActivityUsers, todoActivityUserNameLookupOf, withPageUsers, type TodoActivityEntry } from './activity_users';

/**
 * アクティビティの状態と操作。items の要素は TodoActivityRead にページの users (page_users) を付けたもの。
 */
export type TodoActivitiesState = CursorListState<TodoActivityEntry> & {
    /** 読み込み済みの全ページが参照するユーザー (ユーザー ID → 表示名・有効/無効)。取得前・失敗時は空。 */
    users: TodoActivityUsers;
    /**
     * ユーザー ID から表示名を引く (引けなければ「不明なユーザー」)。画面の NameLookup にそのまま渡せる。
     * @param {string} user_id ユーザー ID
     * @returns {string} 表示名
     */
    userName: (user_id: string) => string;
};

export type UseTodoActivitiesOptions = {
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
};

/**
 * ToDo のアクティビティを取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {string} todo_id ToDo ID
 * @param {UseTodoActivitiesOptions} options 件数
 * @returns {TodoActivitiesState} 一覧の状態と操作
*/
export const useTodoActivities = (todo_id: string, { limit }: UseTodoActivitiesOptions = {}): TodoActivitiesState => {
    const client = useAppApiClient();
    const query: TodoActivityListQuery = limit !== undefined ? { limit } : {};
    const list = useCursorList<TodoActivityEntry>({
        query_key: `app-todo-activities:${buildTodoActivitiesUrl(todo_id, query)}`,
        fetchPage: async (cursor) => {
            const page = await fetchTodoActivityPage(client, todo_id, cursor === null ? query : { ...query, cursor });
            return { items: withPageUsers(page.items, page.users), next_cursor: page.next_cursor, total: page.total };
        },
        classify: classifyAppError,
    });
    const users = useMemo(() => mergeTodoActivityUsers(list.items), [list.items]);
    const userName = useMemo(() => todoActivityUserNameLookupOf(users), [users]);
    return { ...list, users, userName };
};

export default useTodoActivities;
