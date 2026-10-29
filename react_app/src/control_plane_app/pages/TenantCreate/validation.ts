// テナント作成フォームの入力検査と、API のリクエスト・エラーとの対応 (純粋関数)
// テナントコードの形式・予約語は shared/tenant_code.ts で事前に確認する。最終的な判定はサーバー (422 / 409) が行う。
import { CP_PROBLEM_CODE, type InitialAdminInput, type TenantCreate } from '@/control_plane_app/api/contract';
import type { CpErrorInfo } from '@/control_plane_app/api/errors';
import { normalizeTenantCodeInput, tenantCodeViolationOf, type TenantCodeViolation } from '@/shared/tenant_code';

/** 入力欄の値 (すべて文字列) */
export type TenantCreateForm = {
    tenant_code: string;
    name: string;
    email: string;
    last_name: string;
    first_name: string;
};

export type TenantCreateField = keyof TenantCreateForm;

/** 項目ごとのエラーメッセージ */
export type TenantCreateErrors = Partial<Record<TenantCreateField, string>>;

/** 入力欄の並び順 (最初のエラーにフォーカスを移すために使う) */
export const TENANT_CREATE_FIELDS: readonly TenantCreateField[] = ['tenant_code', 'name', 'email', 'last_name', 'first_name'];

export const EMPTY_TENANT_CREATE_FORM: TenantCreateForm = { tenant_code: '', name: '', email: '', last_name: '', first_name: '' };

export const NAME_MAX_LENGTH = 100;
export const EMAIL_MIN_LENGTH = 3;
export const EMAIL_MAX_LENGTH = 254;

const TENANT_CODE_MESSAGE: Record<TenantCodeViolation, string> = {
    empty: 'テナントコードを入力してください。',
    format: 'テナントコードは、英小文字・数字・ハイフンの 3〜32 文字で指定してください (先頭・末尾・連続のハイフンは使えません)。',
    reserved: 'このテナントコードは予約語のため使えません。別のコードを指定してください。',
};

/** 初期管理者の入力欄の値 (払い出しの再実行でも使う) */
export type InitialAdminForm = Pick<TenantCreateForm, 'email' | 'last_name' | 'first_name'>;

/**
 * 初期管理者の入力を検査する関数
 * @param {InitialAdminForm} form 入力欄の値
 * @returns {TenantCreateErrors} 項目ごとのエラー (問題が無ければ空)
*/
export const validateInitialAdminForm = (form: InitialAdminForm): TenantCreateErrors => {
    const errors: TenantCreateErrors = {};
    const email = form.email.trim();
    if (email === '') errors.email = '初期管理者のメールアドレスを入力してください。';
    else if (!/^[^\s@]+@[^\s@]+$/.test(email) || email.length < EMAIL_MIN_LENGTH || email.length > EMAIL_MAX_LENGTH) errors.email = 'メールアドレスの形式で入力してください (254 文字以内)。';
    if (form.last_name.trim().length > NAME_MAX_LENGTH) errors.last_name = `姓は ${NAME_MAX_LENGTH} 文字以内で入力してください。`;
    if (form.first_name.trim().length > NAME_MAX_LENGTH) errors.first_name = `名は ${NAME_MAX_LENGTH} 文字以内で入力してください。`;
    return errors;
};

/**
 * 初期管理者の入力欄の値を API のリクエストにする関数 (姓・名は空なら送らない)
 * @param {InitialAdminForm} form 入力欄の値
 * @returns {InitialAdminInput} リクエスト
*/
export const toInitialAdminInput = (form: InitialAdminForm): InitialAdminInput => ({
    email: form.email.trim(),
    ...(form.last_name.trim() !== '' ? { last_name: form.last_name.trim() } : {}),
    ...(form.first_name.trim() !== '' ? { first_name: form.first_name.trim() } : {}),
});

/**
 * フォームの入力を検査する関数
 * @param {TenantCreateForm} form 入力欄の値
 * @returns {TenantCreateErrors} 項目ごとのエラー (問題が無ければ空)
*/
export const validateTenantCreateForm = (form: TenantCreateForm): TenantCreateErrors => {
    const errors: TenantCreateErrors = {};
    const violation = tenantCodeViolationOf(normalizeTenantCodeInput(form.tenant_code));
    if (violation) errors.tenant_code = TENANT_CODE_MESSAGE[violation];
    const name = form.name.trim();
    if (name === '') errors.name = 'テナント名を入力してください。';
    else if (name.length > NAME_MAX_LENGTH) errors.name = `テナント名は ${NAME_MAX_LENGTH} 文字以内で入力してください。`;
    return { ...errors, ...validateInitialAdminForm(form) };
};

/**
 * 入力欄の値を API のリクエストにする関数 (テナントコードは前後の空白を除いて小文字にする。姓・名は空なら送らない)
 * @param {TenantCreateForm} form 入力欄の値
 * @returns {TenantCreate} リクエスト
*/
export const toTenantCreate = (form: TenantCreateForm): TenantCreate => ({
    tenant_code: normalizeTenantCodeInput(form.tenant_code),
    name: form.name.trim(),
    initial_admin: toInitialAdminInput(form),
});

/** API の項目名 (末尾) と入力欄の対応 */
const SERVER_FIELD_MAP: Record<string, TenantCreateField> = {
    tenant_code: 'tenant_code',
    name: 'name',
    email: 'email',
    last_name: 'last_name',
    first_name: 'first_name',
};

/**
 * API のエラー (422 の項目エラー・409 のテナントコード重複) を、入力欄ごとのエラーにする関数
 * @param {CpErrorInfo} info 分類済みのエラー
 * @returns {TenantCreateErrors} 項目ごとのエラー (対応する入力欄が無ければ空)
*/
export const serverErrorsToFormErrors = (info: CpErrorInfo): TenantCreateErrors => {
    const errors: TenantCreateErrors = {};
    if (info.code === CP_PROBLEM_CODE.TENANT_CODE_ALREADY_EXISTS) errors.tenant_code = 'このテナントコードは既に使われています (削除済みのコードも再利用できません)。';
    if (info.code === CP_PROBLEM_CODE.INVALID_TENANT_CODE) errors.tenant_code = TENANT_CODE_MESSAGE.format;
    for (const item of info.problem?.errors ?? []) {
        const field = SERVER_FIELD_MAP[item.field.split('.').pop() ?? ''];
        if (field && errors[field] === undefined) errors[field] = item.message;
    }
    return errors;
};
