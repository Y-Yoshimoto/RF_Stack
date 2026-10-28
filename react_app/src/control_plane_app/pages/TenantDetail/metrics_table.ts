// メトリクス推移の表示用の整形 (日付 × 指標の表にする。値は 10 進数の文字列のまま扱う)
import type { DailyMetricRead } from '@/control_plane_app/api/contract';
import { groupMetricsByKey } from '@/control_plane_app/api/metrics';

/** 表の 1 行 (1 日分) */
export type MetricsRow = {
    date: string;
    /** 指標のキー → 値 (その日に値が無い指標は含まない) */
    values: Record<string, string>;
};

/**
 * 表の形。
 */
export type MetricsTable = {
    /** 列にする指標のキー (キーの昇順) */
    keys: string[];
    /** 行 (新しい日付が先頭) */
    rows: MetricsRow[];
};

/**
 * 日次メトリクスを、日付 × 指標の表にする関数
 * @param {readonly DailyMetricRead[]} items 日次メトリクス
 * @returns {MetricsTable} 表
*/
export const buildMetricsTable = (items: readonly DailyMetricRead[]): MetricsTable => {
    const series = groupMetricsByKey(items);
    const by_date = new Map<string, Record<string, string>>();
    for (const [metric_key, points] of Object.entries(series)) {
        for (const { date, value } of points) {
            by_date.set(date, { ...(by_date.get(date) ?? {}), [metric_key]: value });
        }
    }
    const rows = [...by_date.entries()].map(([date, values]) => ({ date, values })).sort((a, b) => b.date.localeCompare(a.date));
    return { keys: Object.keys(series).sort(), rows };
};
