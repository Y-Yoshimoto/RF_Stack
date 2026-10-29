/**
 * @description:
 * フォームの未保存の入力 (下書き) を、サーバーの値の変化に追従させるカスタムフック (AP-UX-07・AP-UX-08)
 * - server (useTodo の todo から作ったフォームの値) が変わると、下書きを rebaseDraft で載せ替える:
 *   触っていない項目は新しい値に、触った項目は入力を残し、他の人の変更と食い違う項目を conflicts に入れる
 * - 別のフォームの保存 (applyUpdate) や 412 の後の refresh で server が変わっても、このフォームの入力は消えない。
 *   そのため `key={version}` でフォームを作り直さない
 * - server は毎回作り直してよい (項目ごとに比べて同じなら何もしない)。配列の項目は equals に集合の比較を渡す
 * - 保存に成功したら、保存した値が server に反映されて下書きと一致するため、dirty は自然に消える
*/
import { useCallback, useState } from 'react';
import { dirtyDraftFields, draftFieldEquals, rebaseDraft, sameDraft, type DraftEquals } from './rebase_draft';

/**
 * 下書きの状態と操作。
 */
export type RebasedDraftState<T> = {
    /** 下書き (server が一度も null でなくなっていない間は null。その後 server が null に戻っても下書きは残す)。 */
    draft: T | null;
    /** 下書きの基準 (最後に載せ替えたときの server の値)。 */
    base: T | null;
    /** base から変えた項目。 */
    dirty_fields: (keyof T & string)[];
    /** 変えた項目がある。 */
    is_dirty: boolean;
    /** 他の人の変更と食い違った項目 (入力を残している。該当の項目を入力し直すか clearConflicts で消える)。 */
    conflicts: (keyof T & string)[];
    /** 項目を入力する (server が null の間は何もしない)。 */
    setField: <K extends keyof T & string>(key: K, value: T[K]) => void;
    /** 下書き全体を置き換える。 */
    setDraft: (draft: T) => void;
    /** 入力を捨てて server の値に戻す。 */
    reset: () => void;
    clearConflicts: () => void;
};

/** 下書きの状態 (base は最後に載せ替えたときの server) */
type DraftSnapshot<T> = {
    base: T;
    draft: T;
    conflicts: (keyof T & string)[];
};

/**
 * 下書きを載せ替える関数 (前の衝突のうち、まだ入力が残っている項目は衝突のままにする)
 * @param {DraftSnapshot<T>} prev 前の状態
 * @param {T} next 新しい server の値
 * @param {DraftEquals<T>} equals 項目ごとの判定
 * @returns {DraftSnapshot<T>} 新しい状態
*/
const rebaseSnapshot = <T extends object>(prev: DraftSnapshot<T>, next: T, equals: DraftEquals<T>): DraftSnapshot<T> => {
    const { draft, conflicts } = rebaseDraft(prev.base, prev.draft, next, equals);
    const still = prev.conflicts.filter((key) => !conflicts.includes(key) && !draftFieldEquals(equals, key, draft[key], next[key]));
    return { base: next, draft, conflicts: [...conflicts, ...still] };
};

const NO_EQUALS = {};

/**
 * 下書きを server の値に追従させるカスタムフック
 * @param {T | null} server サーバーの値から作ったフォームの値 (取得前は null)
 * @param {DraftEquals<T>} equals 項目ごとの判定 (配列の項目に集合の比較を渡す)
 * @returns {RebasedDraftState<T>} 下書きの状態と操作
*/
export const useRebasedDraft = <T extends object>(server: T | null, equals: DraftEquals<T> = NO_EQUALS): RebasedDraftState<T> => {
    const [snapshot, setSnapshot] = useState<DraftSnapshot<T> | null>(server === null ? null : { base: server, draft: server, conflicts: [] });

    // server が (項目の値として) 変わったら、描画中に載せ替える (React の「props の変化に応じた state の調整」)
    let current = snapshot;
    if (server !== null && (current === null || !sameDraft(current.base, server, equals))) {
        current = current === null ? { base: server, draft: server, conflicts: [] } : rebaseSnapshot(current, server, equals);
        setSnapshot(current);
    }

    const setField = useCallback(<K extends keyof T & string>(key: K, value: T[K]) => {
        setSnapshot((prev) => {
            if (prev === null) return prev;
            return { ...prev, draft: { ...prev.draft, [key]: value }, conflicts: prev.conflicts.filter((conflict) => conflict !== key) };
        });
    }, []);
    const setDraft = useCallback((draft: T) => setSnapshot((prev) => (prev === null ? prev : { ...prev, draft })), []);
    const reset = useCallback(() => setSnapshot((prev) => (prev === null ? prev : { ...prev, draft: prev.base, conflicts: [] })), []);
    const clearConflicts = useCallback(() => setSnapshot((prev) => (prev === null ? prev : { ...prev, conflicts: [] })), []);

    const dirty_fields = current === null ? [] : dirtyDraftFields(current.base, current.draft, equals);
    return {
        draft: current?.draft ?? null,
        base: current?.base ?? null,
        dirty_fields,
        is_dirty: dirty_fields.length > 0,
        conflicts: current?.conflicts ?? [],
        setField,
        setDraft,
        reset,
        clearConflicts,
    };
};

export default useRebasedDraft;
