// CP の認証状態のコンテキスト (AP とは別インスタンス。01 §11.2)
import { createContext } from 'react';
import type { SessionState } from '@/shared/auth/type';
import type { CpSession } from './session';

/**
 * CP の認証状態と操作。
 */
export type CpAuthValue = {
    /** CP のセッションの状態。 */
    state: SessionState<CpSession>;
    /** 状態 API を再取得する。 */
    refresh: () => void;
    /** BFF のログイン開始 API へトップレベル遷移する。 */
    login: () => void;
    /** ログアウト API を呼び、ログイン画面 (または認証基盤のログアウト) へトップレベル遷移する。失敗時は reject し、遷移しない。 */
    logout: () => Promise<void>;
    /** API のエラーを認証状態に反映する (401 は再取得してログイン画面へ)。 */
    reportApiError: (error: unknown) => void;
};

export const ControlPlaneAuthContext = createContext<CpAuthValue | null>(null);
