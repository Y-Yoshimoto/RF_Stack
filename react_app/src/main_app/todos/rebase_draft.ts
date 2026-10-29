// 未保存の入力 (下書き) を、サーバーの新しい値に載せ替える関数 (純粋関数。AP-UX-07・AP-UX-08)
// 下書きはフォームの項目ごとの値 (オブジェクト)。base は下書きを作った (前回載せ替えた) ときのサーバーの値。
// - 触っていない項目 (draft と base が同じ) は next の値にする (他の人の変更・別のフォームの保存を取り込む)
// - 触った項目は draft の値を残す。next も base から変わっていて draft と違えば衝突 (conflicts) として知らせる
// 配列 (担当者・公開先組織の ID) のように順序を問わない項目は、equals に集合の比較 (todo_changes.ts の sameIdSet) を渡す。
// フォームのフックは useRebasedDraft.ts。

/** 項目ごとの等しさの判定 (省略した項目は Object.is)。 */
export type DraftEquals<T> = { readonly [K in keyof T]?: (a: T[K], b: T[K]) => boolean };

/**
 * 載せ替えの結果。
 */
export type RebasedDraft<T> = {
    /** 載せ替えた下書き。 */
    draft: T;
    /** 自分も他の人も変えていて、値が食い違う項目 (draft の値を残している)。 */
    conflicts: (keyof T & string)[];
};

/**
 * 項目の値が等しいかを判定する関数
 * @param {DraftEquals<T>} equals 項目ごとの判定
 * @param {K} key 項目
 * @param {T[K]} a 値
 * @param {T[K]} b 値
 * @returns {boolean} 等しければ true
*/
export const draftFieldEquals = <T extends object, K extends keyof T>(equals: DraftEquals<T>, key: K, a: T[K], b: T[K]): boolean => {
    const compare = equals[key];
    return compare !== undefined ? compare(a, b) : Object.is(a, b);
};

/**
 * 項目の一覧を返す関数 (next の項目。文字列のキーのみ)
 * @param {T} value 値
 * @returns {(keyof T & string)[]} 項目
*/
const keysOf = <T extends object>(value: T): (keyof T & string)[] => Object.keys(value) as (keyof T & string)[];

/**
 * 下書きのうち、base から変えた項目を返す関数
 * @param {T} base 下書きを作ったときのサーバーの値
 * @param {T} draft 下書き
 * @param {DraftEquals<T>} equals 項目ごとの判定
 * @returns {(keyof T & string)[]} 変えた項目
*/
export const dirtyDraftFields = <T extends object>(base: T, draft: T, equals: DraftEquals<T> = {}): (keyof T & string)[] => {
    return keysOf(draft).filter((key) => !draftFieldEquals(equals, key, draft[key], base[key]));
};

/**
 * 2 つの値がすべての項目で等しいかを判定する関数
 * @param {T} a 値
 * @param {T} b 値
 * @param {DraftEquals<T>} equals 項目ごとの判定
 * @returns {boolean} 等しければ true
*/
export const sameDraft = <T extends object>(a: T, b: T, equals: DraftEquals<T> = {}): boolean => {
    const keys = new Set([...keysOf(a), ...keysOf(b)]);
    return [...keys].every((key) => draftFieldEquals(equals, key, a[key], b[key]));
};

/**
 * 下書きを新しいサーバーの値に載せ替える関数
 * @param {T} base 下書きを作ったときのサーバーの値
 * @param {T} draft 下書き
 * @param {T} next 新しいサーバーの値
 * @param {DraftEquals<T>} equals 項目ごとの判定 (配列の項目に集合の比較を渡す)
 * @returns {RebasedDraft<T>} 載せ替えた下書きと衝突した項目
*/
export const rebaseDraft = <T extends object>(base: T, draft: T, next: T, equals: DraftEquals<T> = {}): RebasedDraft<T> => {
    const rebased = { ...next };
    const conflicts: (keyof T & string)[] = [];
    for (const key of keysOf(next)) {
        const touched = !draftFieldEquals(equals, key, draft[key], base[key]);
        if (!touched) continue;
        rebased[key] = draft[key];
        const changed_by_others = !draftFieldEquals(equals, key, next[key], base[key]);
        if (changed_by_others && !draftFieldEquals(equals, key, next[key], draft[key])) conflicts.push(key);
    }
    return { draft: rebased, conflicts };
};
