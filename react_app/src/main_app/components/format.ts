// AP の画面で使う表示用の整形関数

const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ja-JP', { dateStyle: 'medium', timeStyle: 'short' });

/**
 * API の日時 (UTC の ISO 8601) を表示用の文字列にする関数
 * @param {string | null | undefined} value 日時 (無ければ null)
 * @param {string} empty_label 値が無いとき (または不正なとき) の表示
 * @returns {string} ブラウザのタイムゾーンでの日時
*/
export const formatDateTime = (value: string | null | undefined, empty_label = '—'): string => {
    if (!value) return empty_label;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? empty_label : DATE_TIME_FORMAT.format(date);
};
