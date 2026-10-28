// AP の API エラー (AppErrorInfo) を、利用者向けの文言にする関数
import { APP_PROBLEM_CODE } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';

/**
 * 画面に出すエラーの文言。
 */
export type AppErrorText = {
    /** 見出し (1 行)。 */
    title: string;
    /** 補足。原因・次にとる行動。 */
    message: string;
    /** 箇条書きの詳細 (項目ごとの入力エラーなど)。 */
    details: string[];
};

/** 自分自身への禁止操作 (409 user_self_modification_forbidden の operation) の表示名 */
const SELF_OPERATION_LABEL: Record<string, string> = {
    deactivate: '自分自身を無効化',
    remove_tenant_admin: '自分自身のテナント管理者ロールを解除',
};

/**
 * 入力検証エラー (422) の項目ごとの詳細を文言にする関数
 * @param {AppErrorInfo} info エラー
 * @returns {string[]} 項目ごとのメッセージ
*/
export const fieldErrorMessagesOf = (info: AppErrorInfo): string[] => (info.problem?.errors ?? []).map((item) => `${item.field}: ${item.message}`);

/**
 * 409 (conflict) の文言を作る関数
 * @param {AppErrorInfo} info エラー
 * @returns {AppErrorText} 文言
*/
const conflictTextOf = (info: AppErrorInfo): AppErrorText => {
    switch (info.code) {
        case APP_PROBLEM_CODE.USER_ALREADY_EXISTS:
            return { title: 'このメールアドレスは既に使われています', message: 'メールアドレスはテナント内で一意にする必要があります。別のメールアドレスを指定してください。', details: [] };
        case APP_PROBLEM_CODE.ORGANIZATION_NAME_ALREADY_EXISTS:
            return { title: 'この組織名は既に使われています', message: '組織名は (大文字小文字を区別せず) 一意にする必要があります。別の名前を指定してください。', details: [] };
        case APP_PROBLEM_CODE.USER_SELF_MODIFICATION_FORBIDDEN: {
            const operation = info.problem?.operation;
            const label = typeof operation === 'string' ? SELF_OPERATION_LABEL[operation] : undefined;
            return { title: label ? `${label}することはできません` : '自分自身には実行できない操作です', message: '締め出しを防ぐため、この操作は別のテナント管理者に依頼してください。', details: [] };
        }
        default:
            return { title: '操作が競合しました', message: info.problem?.detail ?? '最新の状態を読み込んでから、やり直してください。', details: [] };
    }
};

/**
 * 404 (not_found) の文言を作る関数
 * @param {AppErrorInfo} info エラー
 * @returns {AppErrorText} 文言
*/
const notFoundTextOf = (info: AppErrorInfo): AppErrorText => {
    if (info.code === APP_PROBLEM_CODE.USER_NOT_FOUND) return { title: 'ユーザーが見つかりません', message: '存在しないか、このテナントのユーザーではありません。一覧から選び直してください。', details: [] };
    if (info.code === APP_PROBLEM_CODE.ORGANIZATION_NOT_FOUND) return { title: '組織が見つかりません', message: '削除されたか、指定が誤っている可能性があります。一覧から選び直してください。', details: [] };
    return { title: '対象が見つかりません', message: '削除されたか、指定が誤っている可能性があります。', details: [] };
};

/**
 * 422 (invalid_input) の文言を作る関数
 * @param {AppErrorInfo} info エラー
 * @returns {AppErrorText} 文言
*/
const invalidInputTextOf = (info: AppErrorInfo): AppErrorText => {
    if (info.code === APP_PROBLEM_CODE.INVALID_ORGANIZATION_MEMBERS) {
        return { title: 'メンバーに指定できないユーザーが含まれています', message: '削除されたユーザーが含まれている可能性があります。再読み込みして、選び直してください。', details: [] };
    }
    return { title: '入力内容を確認してください', message: info.problem?.detail ?? '入力された値が受け付けられませんでした。', details: fieldErrorMessagesOf(info) };
};

/**
 * AP の API エラーを利用者向けの文言にする関数
 * @param {AppErrorInfo} info 分類済みのエラー
 * @returns {AppErrorText} 文言
*/
export const appErrorTextOf = (info: AppErrorInfo): AppErrorText => {
    switch (info.kind) {
        case 'unauthenticated':
            return { title: 'ログインの有効期限が切れました', message: '再度ログインしてください。', details: [] };
        case 'forbidden':
            return { title: 'この操作を行う権限がありません', message: '変更操作にはテナント管理者の権限が必要です。', details: [] };
        case 'not_found':
            return notFoundTextOf(info);
        case 'version_conflict':
        case 'precondition_required':
            return { title: '他の操作で更新されています', message: '表示している内容が古くなっています。再読み込みして最新の状態を確認してから、やり直してください。', details: [] };
        case 'conflict':
            return conflictTextOf(info);
        case 'invalid_input':
            return invalidInputTextOf(info);
        case 'external_failure':
            return { title: '認証基盤の操作に失敗しました', message: '認証基盤 (Keycloak) との連携で失敗しました。変更は反映されていません。時間をおいて、やり直してください。', details: [] };
        case 'unavailable':
            return { title: 'サービスが一時的に利用できません', message: 'しばらくしてから、やり直してください。', details: [] };
        case 'busy':
            return { title: '別の操作を実行中です', message: '完了してから、やり直してください。', details: [] };
        default:
            return { title: '予期しないエラーが発生しました', message: 'しばらくしてから、やり直してください。解消しない場合は管理者に連絡してください。', details: [] };
    }
};
