// ユーザー作成フォームの入力検証 (純粋関数。API の制約: UserCreate)
import type { AppRole } from '@/main_app/api/contract';

/** メールアドレスの最大長 */
export const EMAIL_MAX_LENGTH = 254;
/** 姓・名の最大長 */
export const NAME_MAX_LENGTH = 100;

/**
 * 入力値 (フォームの状態)。
 */
export type UserCreateValues = {
    email: string;
    last_name: string;
    first_name: string;
    roles: readonly AppRole[];
};

/**
 * 項目ごとのエラー文言 (問題が無い項目は含まない)。
 */
export type UserCreateErrors = Partial<Record<keyof UserCreateValues, string>>;

/** 項目の並び (最初のエラーの項目にフォーカスするため) */
export const USER_CREATE_FIELD_ORDER: readonly (keyof UserCreateValues)[] = ['email', 'last_name', 'first_name', 'roles'];

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * 姓・名の入力を検証する関数
 * @param {string} value 入力値
 * @param {string} label 項目名
 * @returns {string | undefined} エラー文言 (問題が無ければ undefined)
*/
export const nameErrorOf = (value: string, label: string): string | undefined => {
    const trimmed = value.trim();
    if (trimmed === '') return `${label}を入力してください。`;
    if (trimmed.length > NAME_MAX_LENGTH) return `${label}は ${NAME_MAX_LENGTH} 文字以内で入力してください。`;
    return undefined;
};

/**
 * ユーザー作成フォームを検証する関数
 * @param {UserCreateValues} values 入力値
 * @returns {UserCreateErrors} 項目ごとのエラー (空なら問題なし)
*/
export const validateUserCreate = (values: UserCreateValues): UserCreateErrors => {
    const errors: UserCreateErrors = {};
    const email = values.email.trim();
    if (email === '') errors.email = 'メールアドレスを入力してください。';
    else if (email.length > EMAIL_MAX_LENGTH) errors.email = `メールアドレスは ${EMAIL_MAX_LENGTH} 文字以内で入力してください。`;
    else if (!EMAIL_PATTERN.test(email)) errors.email = 'メールアドレスの形式で入力してください。';
    const last_name_error = nameErrorOf(values.last_name, '姓');
    if (last_name_error) errors.last_name = last_name_error;
    const first_name_error = nameErrorOf(values.first_name, '名');
    if (first_name_error) errors.first_name = first_name_error;
    if (values.roles.length === 0) errors.roles = 'ロールを 1 つ以上選んでください。';
    return errors;
};
