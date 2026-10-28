// CP のメトリクス API (`/api/v1/cp/tenants/{id}/metrics`、`/api/v1/cp/metrics/summary`) を呼び出す関数と、表示用の純粋関数
import type { ApiClient } from '@/shared/api/client';
import { CP_API_PATHS, type DailyMetricRead, type MetricsSummaryRead, type TenantMetricsQuery, type TenantMetricsRead } from './contract';

/** 期間を省略したときの日数 (サーバーの既定と同じ。終了日を含む) */
export const DEFAULT_METRICS_RANGE_DAYS = 30;

/** 1 回に取得できる最大の日数 (超えると 422 range_too_long) */
export const MAX_METRICS_RANGE_DAYS = 366;

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * 日付を `YYYY-MM-DD` (UTC) にする関数
 * @param {Date} date 日時
 * @returns {string} 日付
*/
const toUtcDateString = (date: Date): string => date.toISOString().slice(0, 10);

/**
 * 直近 N 日 (今日を含む) の期間を作る関数。日付はサーバーと同じく UTC で数える
 * @param {number} days 日数 (1〜366)
 * @param {Date} now 現在時刻 (テスト用に差し替え可能)
 * @returns {Required<TenantMetricsQuery>} 期間
*/
export const recentMetricsRange = (days: number = DEFAULT_METRICS_RANGE_DAYS, now: Date = new Date()): Required<TenantMetricsQuery> => {
    const span = Math.min(Math.max(Math.trunc(days), 1), MAX_METRICS_RANGE_DAYS);
    return { from: toUtcDateString(new Date(now.getTime() - (span - 1) * DAY_MS)), to: toUtcDateString(now) };
};

/**
 * テナントのメトリクス API の URL を作る関数
 * @param {string} tenant_id テナント ID
 * @param {TenantMetricsQuery} range 期間 (省略した端はサーバーの既定)
 * @returns {string} URL
*/
export const buildTenantMetricsUrl = (tenant_id: string, range: TenantMetricsQuery = {}): string => {
    const params = new URLSearchParams();
    if (range.from) params.set('from', range.from);
    if (range.to) params.set('to', range.to);
    const search = params.toString();
    return search === '' ? CP_API_PATHS.tenantMetrics(tenant_id) : `${CP_API_PATHS.tenantMetrics(tenant_id)}?${search}`;
};

/**
 * テナントの日次メトリクスの推移を取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} tenant_id テナント ID
 * @param {TenantMetricsQuery} range 期間 (省略時は直近 30 日)
 * @returns {Promise<TenantMetricsRead>} 推移
*/
export const fetchTenantMetrics = async (client: ApiClient, tenant_id: string, range: TenantMetricsQuery = {}): Promise<TenantMetricsRead> => {
    const url = buildTenantMetricsUrl(tenant_id, range);
    const body = await client.request<TenantMetricsRead>({ url, method: 'GET' });
    if (!body) throw new Error(`CP API の応答が空です: ${url}`);
    return body;
};

/**
 * 全テナントのサマリーを取得する関数
 * @param {ApiClient} client API クライアント
 * @returns {Promise<MetricsSummaryRead>} サマリー
*/
export const fetchMetricsSummary = async (client: ApiClient): Promise<MetricsSummaryRead> => {
    const body = await client.request<MetricsSummaryRead>({ url: CP_API_PATHS.METRICS_SUMMARY, method: 'GET' });
    if (!body) throw new Error(`CP API の応答が空です: ${CP_API_PATHS.METRICS_SUMMARY}`);
    return body;
};

/**
 * 推移の 1 点 (グラフ用)。
 */
export type MetricPoint = {
    date: string;
    /** 10 進数の文字列のまま (表示・グラフ化の直前に変換する)。 */
    value: string;
};

/**
 * 日次メトリクスを指標ごとの系列 (日付の昇順) にまとめる関数
 * @param {readonly DailyMetricRead[]} items 日次メトリクス
 * @returns {Record<string, MetricPoint[]>} 指標のキー → 系列
*/
export const groupMetricsByKey = (items: readonly DailyMetricRead[]): Record<string, MetricPoint[]> => {
    const series: Record<string, MetricPoint[]> = {};
    for (const { date, metric_key, value } of items) {
        (series[metric_key] ??= []).push({ date, value });
    }
    for (const points of Object.values(series)) points.sort((a, b) => a.date.localeCompare(b.date));
    return series;
};
