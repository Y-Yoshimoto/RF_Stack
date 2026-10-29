/**
 * 新しい画面の E2E 用のフィクスチャ。
 *
 * `openAs(profile)` は、指定した開発用ログインのプロファイル (auth.setup.ts が保存した認証状態) でログイン済みの Page を返す。
 * 1 つのテストに複数の利用者が登場するシナリオ (例: 管理者が作った ToDo をメンバーが操作する) で使う。
 * プロジェクト (Screens Desktop / Screens Mobile) のビューポート・端末設定を引き継ぐため、モバイルでも同じ条件で動く。
 * 開いたコンテキストはテストの終了時に閉じる。
 * (フィクスチャの第 2 引数は慣例では use だが、react-hooks の lint ルールがフックの呼び出しと誤検出するため provide と名付けている。)
 */
import { test as base, type BrowserContext, type Page } from '@playwright/test';
import { authStatePath, type ProfileName } from './constants';

type Fixtures = {
    openAs: (profile: ProfileName) => Promise<Page>;
};

export const test = base.extend<Fixtures>({
    openAs: async ({ browser }, provide, testInfo) => {
        const contexts: BrowserContext[] = [];
        const { baseURL, viewport, userAgent, deviceScaleFactor, isMobile, hasTouch } = testInfo.project.use;
        await provide(async (profile) => {
            const context = await browser.newContext({
                baseURL,
                viewport,
                userAgent,
                deviceScaleFactor,
                isMobile,
                hasTouch,
                storageState: authStatePath(profile),
            });
            contexts.push(context);
            return context.newPage();
        });
        await Promise.all(contexts.map((context) => context.close()));
    },
});

export { expect } from '@playwright/test';
