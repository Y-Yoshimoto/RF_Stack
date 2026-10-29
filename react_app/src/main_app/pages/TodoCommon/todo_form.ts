// ToDo の入力フォームの値と検証 (純粋関数)
import { TODO_DEFAULTS, TODO_LIMITS, type TodoDetail, type TodoPriority, type TodoStatus } from '@/main_app/api/contract';
import { isIsoDate } from '@/main_app/todos/list_search';

/**
 * 項目の入力値 (フォームの状態)。期限は空文字で「なし」。
 */
export type TodoFieldValues = {
    title: string;
    description: string;
    due_date: string;
    priority: TodoPriority;
    status: TodoStatus;
};

/** 検証の対象で、フォーカスできる入力欄 */
export type TodoFieldKey = 'title' | 'description' | 'due_date';

export type TodoFieldErrors = Partial<Record<TodoFieldKey, string>>;

/** 検証でエラーを探す順 (最初のエラーにフォーカスする) */
export const TODO_FIELD_ORDER: readonly TodoFieldKey[] = ['title', 'description', 'due_date'];

/** 新規作成の初期値 (AP-TODO-02 / 03) */
export const INITIAL_TODO_FIELDS: TodoFieldValues = { title: '', description: '', due_date: '', priority: TODO_DEFAULTS.PRIORITY, status: TODO_DEFAULTS.STATUS };

/**
 * 詳細から入力値を作る関数
 * @param {TodoDetail} todo 詳細
 * @returns {TodoFieldValues} 入力値
*/
export const fieldValuesOf = (todo: TodoDetail): TodoFieldValues => ({
    title: todo.title,
    description: todo.description ?? '',
    due_date: todo.due_date ?? '',
    priority: todo.priority,
    status: todo.status,
});

/**
 * 入力値を検証する関数 (AP-TODO-04: タイトルは必須で 1〜200 文字、説明は最大 10,000 文字、期限は実在する日付)
 * @param {TodoFieldValues} values 入力値
 * @returns {TodoFieldErrors} 項目ごとのエラー (無ければ空)
*/
export const validateTodoFields = (values: TodoFieldValues): TodoFieldErrors => {
    const errors: TodoFieldErrors = {};
    const title = values.title.trim();
    if (title === '') errors.title = 'タイトルを入力してください。';
    else if (title.length > TODO_LIMITS.TITLE_MAX) errors.title = `タイトルは ${TODO_LIMITS.TITLE_MAX} 文字以内で入力してください。`;
    if (values.description.length > TODO_LIMITS.DESCRIPTION_MAX) errors.description = `説明は ${TODO_LIMITS.DESCRIPTION_MAX.toLocaleString('ja-JP')} 文字以内で入力してください。`;
    if (values.due_date !== '' && !isIsoDate(values.due_date)) errors.due_date = '期限は日付の形式 (年-月-日) で入力してください。';
    return errors;
};
