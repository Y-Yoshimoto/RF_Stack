/**
 * @description:
 * 変更操作 (API 呼び出し) の実行状態を管理するカスタムフック (プレーン共通)
 * - 同じフックでの二重実行は API を呼ばずに失敗にする (busy)
 * - 実行前の確認 (権限・ETag・業務上の禁止操作) で弾いた場合も API を呼ばずに失敗にする
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
 * プレーンの操作フック (useUserActions・useOrganizationActions) が、エラー分類と失敗の形を渡して使う。
*/
import { useCallback, useRef, useState } from 'react';
import type { ApiErrorInfo, ApiGuardError } from '@/shared/api/errors';

/**
 * 実行する操作。
 */
export type ActionPlan<A extends string, R> = {
    action: A;
    /** 失敗の対象 (リソース ID。作成など対象が無い場合は null)。 */
    target_id: string | null;
    /** 実行前の確認。弾く場合は理由の例外を返す (API は呼ばない)。 */
    precheck?: () => ApiGuardError | null;
    /** API 呼び出し。 */
    run: () => Promise<R>;
};

/**
 * 操作の結果。
 */
export type ActionOutcome<R, F> = { ok: true; value: R } | { ok: false; failure: F };

export type UseActionRunnerParams<A extends string, F> = {
    /** エラーの分類 (プレーンごと)。 */
    classify: (error: unknown) => ApiErrorInfo;
    /** 分類したエラーを、操作の失敗の形にする関数。 */
    toFailure: (info: ApiErrorInfo, action: A, target_id: string | null) => F;
    /** 二重実行を表す例外を作る関数。 */
    busyError: () => ApiGuardError;
    /** 操作の開始時 (二重実行でないことを確かめた後、実行前の確認の前) に呼ばれる。前の操作の結果の破棄に使う。 */
    onStart?: () => void;
};

/**
 * 実行状態と操作。
 */
export type ActionRunner<A extends string, F> = {
    /** 実行中の操作 (無ければ null)。 */
    pending: A | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: F | null;
    clearFailure: () => void;
    /** 操作を実行する。 */
    execute: <R>(plan: ActionPlan<A, R>) => Promise<ActionOutcome<R, F>>;
};

/**
 * 変更操作の実行状態を管理するカスタムフック
 * @param {UseActionRunnerParams<A, F>} params エラー分類・失敗の形・二重実行の例外・開始時の処理
 * @returns {ActionRunner<A, F>} 実行状態と操作
*/
export const useActionRunner = <A extends string, F>({ classify, toFailure, busyError, onStart }: UseActionRunnerParams<A, F>): ActionRunner<A, F> => {
    const [pending, setPending] = useState<A | null>(null);
    const [failure, setFailure] = useState<F | null>(null);
    // 二重実行を防ぐ (イベントハンドラーからのみ読み書きする)
    const is_running = useRef(false);

    const execute = useCallback(async <R,>(plan: ActionPlan<A, R>): Promise<ActionOutcome<R, F>> => {
        const fail = (error: unknown): ActionOutcome<R, F> => {
            const info = toFailure(classify(error), plan.action, plan.target_id);
            setFailure(info);
            return { ok: false, failure: info };
        };
        if (is_running.current) return fail(busyError());
        setFailure(null);
        onStart?.();
        const rejected = plan.precheck?.() ?? null;
        if (rejected !== null) return fail(rejected);
        is_running.current = true;
        setPending(plan.action);
        try {
            return { ok: true, value: await plan.run() };
        } catch (error) {
            return fail(error);
        } finally {
            is_running.current = false;
            setPending(null);
        }
    }, [classify, toFailure, busyError, onStart]);

    const clearFailure = useCallback(() => setFailure(null), []);
    return { pending, failure, clearFailure, execute };
};

export default useActionRunner;
