/**
 * 使い捨てデータの後片付け (teardown)。
 *
 * playwright.config.ts で `setup` プロジェクトの `teardown` に指定している。依存する全プロジェクト (Chrome * / Screens *) の完了後に 1 回だけ実行され、
 * 画面の E2E (screens/) が作る使い捨てのテナント (e2e-<suffix>)・ユーザー・ToDo・組織を、FastAPI の開発専用 API で削除する。
 * テストが途中で失敗して個別の後片付けが走らなかった場合も、ここで消える。
 *
 * - 認証は cp-admin (saas_admin) の認証状態 (auth.setup.ts が保存) を使う。
 * - 変更系の API は CSRF 対策で Origin が FRONTEND_URL (dev サーバー = SCREEN_BASEURL) のものでないと拒否されるため、SCREEN_BASEURL 経由で呼ぶ。
 * - 後片付けの失敗でテストを赤にしない。409 (実行中) は 1 回だけ待って再試行し、それ以外の失敗は警告を出して終える。
 * - Keycloak のプロジェクト (E2E_KEYCLOAK=1) は setup も teardown も使わず、データを作らないため呼ばない。
 */
import { test as teardown, request as playwrightRequest } from '@playwright/test';
import { authStatePath, SCREEN_BASEURL } from './constants';

/** 後片付け API のパス。開発専用機能が無効のときは 404 になる */
const CLEANUP_PATH = '/api/dev/e2e-cleanup';
/** 409 (別の後片付けが実行中) のときに待つ時間 (ミリ秒) */
const RETRY_WAIT_MS = 5_000;
/** 後片付けは同期処理で、テナント数に比例して時間がかかる */
const CLEANUP_TIMEOUT_MS = 240_000;

type CleanupResult = {
    dry_run: boolean;
    tenants: { deprovisioned: unknown[] | number; reaped: unknown[] | number; skipped: unknown[] | number; failed: unknown[] | number };
    app_tenants: Record<string, unknown>[];
    failures: unknown[];
    ok: boolean;
};

/** 配列なら長さ、数値ならその値を返す */
const countOf = (value: unknown): number => (Array.isArray(value) ? value.length : typeof value === 'number' ? value : 0);

/** AP のテナントごとの件数を合計する */
const sumApp = (result: CleanupResult, key: string): number => result.app_tenants.reduce((total, item) => total + countOf(item[key]), 0);

const warn = (message: string): void => console.warn(`[teardown] 警告: ${message}`);

teardown('使い捨てデータを後片付けする', async () => {
    teardown.setTimeout(CLEANUP_TIMEOUT_MS + RETRY_WAIT_MS + 30_000);
    try {
        const context = await playwrightRequest.newContext({
            baseURL: SCREEN_BASEURL,
            storageState: authStatePath('cp-admin'),
            extraHTTPHeaders: { 'X-Requested-With': 'rf-stack', Origin: new URL(SCREEN_BASEURL).origin },
        });
        try {
            let response = await context.post(CLEANUP_PATH, { timeout: CLEANUP_TIMEOUT_MS });
            if (response.status() === 409) {
                warn(`後片付けが実行中 (HTTP 409) のため ${RETRY_WAIT_MS / 1000} 秒後に 1 回だけ再試行します`);
                await new Promise((resolve) => setTimeout(resolve, RETRY_WAIT_MS));
                response = await context.post(CLEANUP_PATH, { timeout: CLEANUP_TIMEOUT_MS });
            }
            if (!response.ok()) {
                const hint = response.status() === 404 ? ' (開発専用機能が無効、または API が未提供です)' : '';
                warn(`後片付けに失敗しました (HTTP ${response.status()})${hint}。使い捨てデータが残っている可能性があります`);
                return;
            }
            const result = (await response.json()) as CleanupResult;
            const { tenants } = result;
            console.log(
                `[teardown] 後片付け: テナント削除 ${countOf(tenants.deprovisioned)} / 回収 ${countOf(tenants.reaped)} / スキップ ${countOf(tenants.skipped)} / 失敗 ${countOf(tenants.failed)}, ` +
                    `AP ユーザー ${sumApp(result, 'users')} / 組織 ${sumApp(result, 'organizations')} / ToDo ${sumApp(result, 'todos')}, failures ${result.failures.length}, ok=${result.ok}`,
            );
            if (!result.ok) warn(`後片付けで失敗がありました (failures ${result.failures.length} 件)。残ったデータは次回の実行で再度対象になります`);
        } finally {
            await context.dispose();
        }
    } catch (error) {
        warn(`後片付けを実行できませんでした (${error instanceof Error ? error.message : String(error)})`);
    }
});
