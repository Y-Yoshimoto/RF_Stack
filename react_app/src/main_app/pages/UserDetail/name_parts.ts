// 表示名から姓・名の入力欄の初期値を作る関数
// API は姓・名を返さず、表示名を `"{名} {姓}"` の形で返す。編集フォームの初期値はこの形から推定する (推定が外れうるため、入力欄を変更したときだけ姓名を送る)。

/**
 * 姓・名の組。
 */
export type NameParts = {
    first_name: string;
    last_name: string;
};

/**
 * 表示名 (`"{名} {姓}"`) を名と姓に分ける関数 (最初の空白で分ける。空白が無ければ全体を名とする)
 * @param {string} display_name 表示名
 * @returns {NameParts} 名と姓
*/
export const namePartsOf = (display_name: string): NameParts => {
    const trimmed = display_name.trim();
    const index = trimmed.search(/\s/);
    if (index < 0) return { first_name: trimmed, last_name: '' };
    return { first_name: trimmed.slice(0, index), last_name: trimmed.slice(index).trim() };
};
