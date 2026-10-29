// ToDo の画面で、ユーザー (作成者・更新者・コメントの投稿者・完了した人) を文字にする関数 (純粋関数)
import type { TodoUserRef } from '@/main_app/api/contract';

/** 無効化されたユーザーに添える表示 (色だけに頼らない) */
export const INACTIVE_USER_SUFFIX = '(無効)';

/**
 * ユーザーを表示用の文字にする関数 (無効化されたユーザーは名前に「(無効)」を添える)
 * @param {TodoUserRef} user ユーザー
 * @returns {string} 表示用の文字
*/
export const todoUserTextOf = (user: TodoUserRef): string => (user.is_active ? user.display_name : `${user.display_name} ${INACTIVE_USER_SUFFIX}`);
