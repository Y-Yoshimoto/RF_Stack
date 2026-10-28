// CP の画面で使う表示用の定義 (テナントの状態・指標・払い出しの表示名と、日時・件数の整形)
import type { ProvisioningType, RunStatus, TenantStatus } from '@/control_plane_app/api/contract';

/** 状態の表示順 (絞り込み・サマリーで使う) */
export const TENANT_STATUSES: readonly TenantStatus[] = ['ACTIVE', 'PROVISIONING', 'SUSPENDED', 'FAILED', 'PENDING_DELETION', 'DEPROVISIONING', 'DELETED'];

/** 状態の表示 (色だけに頼らず、必ず文言も出す) */
export const TENANT_STATUS_LABEL: Record<TenantStatus, string> = {
    PROVISIONING: '払い出し中',
    ACTIVE: '稼働中',
    FAILED: '払い出し失敗',
    SUSPENDED: '停止中',
    PENDING_DELETION: '削除待ち',
    DEPROVISIONING: '削除処理中',
    DELETED: '削除済み',
};

/** 状態の色 (MUI の Chip の color) */
export const TENANT_STATUS_COLOR: Record<TenantStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    PROVISIONING: 'info',
    ACTIVE: 'success',
    FAILED: 'error',
    SUSPENDED: 'warning',
    PENDING_DELETION: 'warning',
    DEPROVISIONING: 'warning',
    DELETED: 'default',
};

/** 状態に説明を付けた文言 (詳細画面で使う) */
export const TENANT_STATUS_NOTE: Record<TenantStatus, string> = {
    PROVISIONING: '払い出しの実行中です。',
    ACTIVE: 'テナントの利用者は通常どおりログインして利用できます。',
    FAILED: '払い出しが途中で失敗しました。原因を確認して再実行できます。',
    SUSPENDED: '認証領域が無効化されており、テナントの利用者はログインも API の利用もできません。',
    PENDING_DELETION: '削除が要求されています。猶予期間中はデータを保持し、経過後に物理削除されます。',
    DEPROVISIONING: '猶予期間を過ぎ、認証領域とデータを削除しています。',
    DELETED: '削除済みです。テナントコードは再利用できません。',
};

/**
 * 状態の表示名を返す関数 (未知の値はそのまま返す)
 * @param {string} status 状態
 * @returns {string} 表示名
*/
export const tenantStatusLabelOf = (status: string): string => (TENANT_STATUS_LABEL as Record<string, string>)[status] ?? status;

/** 指標のキーの表示名 (テーマ固有の指標は、ここに追加する。無いキーはキーをそのまま表示する) */
export const METRIC_LABEL: Record<string, string> = {
    todo_count: 'ToDo 数',
    todo_open_count: 'ToDo オープン数',
    todo_in_progress_count: 'ToDo 進行中',
    todo_done_count: 'ToDo 完了数',
    users_total: 'ユーザー数 (総数)',
    users_active: 'ユーザー数 (有効)',
};

/**
 * 指標の表示名を返す関数
 * @param {string} metric_key 指標のキー
 * @returns {string} 表示名
*/
export const metricLabelOf = (metric_key: string): string => METRIC_LABEL[metric_key] ?? metric_key;

/** 払い出しの種類の表示名 */
export const PROVISIONING_TYPE_LABEL: Record<ProvisioningType, string> = { onboard: '払い出し', offboard: '払い出し解除' };

/** 払い出しの実行状態の表示 */
export const RUN_STATUS_LABEL: Record<RunStatus, string> = { RUNNING: '実行中', SUCCEEDED: '成功', FAILED: '失敗', SKIPPED: 'スキップ' };

/** 払い出しの実行状態の色 */
export const RUN_STATUS_COLOR: Record<RunStatus, 'default' | 'success' | 'error' | 'info'> = { RUNNING: 'info', SUCCEEDED: 'success', FAILED: 'error', SKIPPED: 'default' };

/**
 * 日時 (UTC の ISO 8601) を利用者の地域の表記にする関数
 * @param {string | null | undefined} value 日時
 * @returns {string} 表記。値が無い、または日時として解釈できない場合は「—」(解釈できない値はそのまま返す)
*/
export const formatDateTime = (value: string | null | undefined): string => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('ja-JP', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

/**
 * 10 進数の文字列を桁区切りにする関数 (浮動小数点に変換しない。整数部だけに区切りを入れる)
 * @param {string | null | undefined} value 値
 * @returns {string} 表記。値が無い場合は「—」
*/
export const formatMetricValue = (value: string | null | undefined): string => {
    if (value === null || value === undefined || value === '') return '—';
    const matched = /^(-?)(\d+)(\.\d+)?$/.exec(value);
    if (!matched) return value;
    return `${matched[1]}${matched[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${matched[3] ?? ''}`;
};

/** 変更操作の表示名 */
export const ACTION_LABEL: Record<string, string> = {
    create: 'テナントの作成',
    suspend: '停止',
    resume: '再開',
    request_deletion: '削除要求',
    retry: '払い出しの再実行',
};
