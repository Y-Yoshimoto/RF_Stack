// ToDo のコメントの、API を呼ぶ前の確認 (純粋関数。AP-CMT)
// - 投稿は ToDo の permissions.can_comment、編集・削除はコメントごとの permissions (can_edit / can_delete) で判定する
// - 本文はプレーンテキストで 1〜4,000 文字 (空白だけは不可)。送る本文は入力のまま (前後の空白も残す)
// useTodoComments が使う。画面は isValidCommentBody で投稿ボタンを出し分けられる。
import { TODO_LIMITS, type TodoCommentRead } from '@/main_app/api/contract';
import { AppGuardError } from '@/main_app/api/errors';
import { TodoGuardError } from './todo_changes';

/**
 * コメントの本文として送れるかを判定する関数 (空白だけでなく、4,000 文字以内)
 * @param {string} body 本文
 * @returns {boolean} 送れるなら true
*/
export const isValidCommentBody = (body: string): boolean => body.trim() !== '' && body.length <= TODO_LIMITS.COMMENT_BODY_MAX;

/**
 * 投稿の前に弾く理由を返す関数 (権限 → 本文の順)
 * @param {string} body 本文
 * @param {boolean | undefined} can_comment ToDo の permissions.can_comment (分からなければ undefined。API に任せる)
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const commentCreateGuardOf = (body: string, can_comment: boolean | undefined): AppGuardError | null => {
    if (can_comment === false) return new AppGuardError('write_not_allowed');
    if (!isValidCommentBody(body)) return new AppGuardError('todo_comment_body_invalid');
    return null;
};

/**
 * 編集の前に弾く理由を返す関数 (権限 → 本文 → 変更なしの順)
 * @param {TodoCommentRead} comment 対象のコメント (一覧の要素)
 * @param {string} body 新しい本文
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const commentUpdateGuardOf = (comment: TodoCommentRead, body: string): AppGuardError | null => {
    if (!comment.permissions.can_edit) return new TodoGuardError('edit_comment');
    if (!isValidCommentBody(body)) return new AppGuardError('todo_comment_body_invalid');
    if (body === comment.body) return new AppGuardError('empty_changes');
    return null;
};

/**
 * 削除の前に弾く理由を返す関数
 * @param {TodoCommentRead} comment 対象のコメント (一覧の要素)
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const commentRemoveGuardOf = (comment: TodoCommentRead): AppGuardError | null => (comment.permissions.can_delete ? null : new TodoGuardError('delete_comment'));
