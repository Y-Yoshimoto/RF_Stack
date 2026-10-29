// ログイン画面・ランディングの `?error=<code>` を利用者向けの文言に対応させる
// コードの一覧の正は FastAPI の modules/auth/redirects.py (LoginErrorCode)。詳細な理由はサーバーのログにだけ残る。
import { LOGIN_ERROR_CODE } from './type';

/** 一覧に無いコードの文言 */
export const DEFAULT_LOGIN_ERROR_MESSAGE = 'ログインできませんでした。時間をおいてもう一度お試しください';

/** エラーコードと文言の対応 */
export const LOGIN_ERROR_MESSAGES: Readonly<Record<string, string>> = {
    [LOGIN_ERROR_CODE.TENANT_UNAVAILABLE]: 'このテナントは利用できません。テナントコードを確認してください',
    [LOGIN_ERROR_CODE.INVALID_AUTH_STATE]: 'ログインの有効期限が切れました。もう一度ログインしてください',
    [LOGIN_ERROR_CODE.AUTHORIZATION_FAILED]: 'ログインが完了しませんでした。もう一度ログインしてください',
    [LOGIN_ERROR_CODE.TOKEN_EXCHANGE_FAILED]: 'ログインを完了できませんでした。もう一度ログインしてください',
    [LOGIN_ERROR_CODE.INVALID_TOKEN]: '認証情報を確認できませんでした。もう一度ログインしてください',
    [LOGIN_ERROR_CODE.LOGIN_REJECTED]: 'このアカウントではログインできません。管理者に確認してください',
    [LOGIN_ERROR_CODE.IDENTITY_PROVIDER_UNREACHABLE]: '認証サーバーに接続できません。時間をおいてもう一度お試しください',
    [LOGIN_ERROR_CODE.SERVICE_UNAVAILABLE]: 'サービスを一時的に利用できません。時間をおいてもう一度お試しください',
    [LOGIN_ERROR_CODE.INTERNAL_ERROR]: 'エラーが発生しました。時間をおいてもう一度お試しください',
};

/**
 * エラーコードを利用者向けの文言にする関数
 * @param {string | null} code エラーコード (`?error=` の値)
 * @returns {string | null} 文言 (コードが無ければ null、未知のコードは汎用の文言)
*/
export const loginErrorMessageOf = (code: string | null): string | null => {
    if (!code) return null;
    return Object.hasOwn(LOGIN_ERROR_MESSAGES, code) ? LOGIN_ERROR_MESSAGES[code] : DEFAULT_LOGIN_ERROR_MESSAGE;
};
