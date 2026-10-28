/**
 * @description:
 * ランディング (`/`) のテナントコード入力のロジック
 * 入力を検証し、`/{tenant_code}/login` へ遷移する。存在確認は遷移先のログイン画面で行う。
*/
import { useNavigate } from 'react-router-dom';
import { appLoginPath } from '@/main_app/paths';
import { useErrorQuery } from '@/shared/routing/useErrorQuery';
import { normalizeTenantCodeInput, tenantCodeViolationOf, type TenantCodeViolation } from '@/shared/tenant_code';

/**
 * 入力値の検証結果。
 */
export type TenantCodeEntryResult =
    | { ok: true; tenant_code: string }
    | { ok: false; violation: TenantCodeViolation };

/**
 * テナントコードの入力値を検証する関数
 * 予約語も形式違反と同様に受け付けない (画面ではまとめて「テナントコードが正しくありません」としてよい)。
 * @param {string} input 入力値
 * @returns {TenantCodeEntryResult} 検証結果
*/
export const parseTenantCodeEntry = (input: string): TenantCodeEntryResult => {
    const tenant_code = normalizeTenantCodeInput(input);
    const violation = tenantCodeViolationOf(tenant_code);
    return violation === null ? { ok: true, tenant_code } : { ok: false, violation };
};

/**
 * ランディングのテナントコード入力のカスタムフック
 * @returns {{ error_code: string | null, submit: (input: string) => TenantCodeEntryResult }}
 *     error_code: クエリ `?error=` (例: tenant_unavailable)。submit: 検証し、成功ならログイン画面へ遷移する
*/
export const useTenantCodeEntry = () => {
    const navigate = useNavigate();
    const error_code = useErrorQuery();
    const submit = (input: string): TenantCodeEntryResult => {
        const result = parseTenantCodeEntry(input);
        if (result.ok) navigate(appLoginPath(result.tenant_code));
        return result;
    };
    return { error_code, submit };
};

export default useTenantCodeEntry;
