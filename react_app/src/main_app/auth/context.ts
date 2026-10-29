// AP の認証状態のコンテキスト (CP とは別インスタンス。01 §11.2)
import { createContext } from 'react';
import type { SessionState } from '@/shared/auth/type';
import type { TenantBlockReason } from './guard';
import type { AppSession } from './session';

/**
 * AP の認証状態と操作。
 */
export type AppAuthValue = {
    /** AP のセッションの状態。 */
    state: SessionState<AppSession>;
    /** API の 403 で分かったテナントの利用不可 (無ければ null)。 */
    blocked: TenantBlockReason | null;
    /** 状態 API を再取得する。 */
    refresh: () => void;
    /** BFF のログイン開始 API へトップレベル遷移する。 */
    login: (tenant_code: string) => void;
    /** ログアウト API を呼び、ログイン画面 (または認証基盤のログアウト) へトップレベル遷移する。失敗時は reject し、遷移しない。 */
    logout: () => Promise<void>;
    /** API のエラーを認証状態に反映する (401 は再取得、403 tenant_inactive / tenant_unavailable は利用不可)。 */
    reportApiError: (error: unknown) => void;
};

export const AppAuthContext = createContext<AppAuthValue | null>(null);
