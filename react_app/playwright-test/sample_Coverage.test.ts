// カバレッジを取得して、v8toIstanbulを使用してIstanbul形式に変換するサンプルコード
// console.log('Playwrightでカバレッジを取得して、v8toIstanbulを使用してIstanbul形式に変換するサンプルコードです。');
// eslintでこのファイル自体を無視する
/* eslint-disable */
import { test, expect } from '@playwright/test';
import { chromium } from '@playwright/test'; // Playwrightのデフォルトのブラウザを使用
import v8ToIstanbul from 'v8-to-istanbul';
import fs from 'fs';
import nyc from 'nyc';

// ToDo: カバレッジ測定のJsonをnycで読み取り変換する
/*
test('カバレッジ収集', async ({ page }: { page }, testInfo) => {
    console.log('Playwrightのテストを開始します。');
    const browser = await chromium.launch();
    await page.coverage.startJSCoverage();
    await page.goto('/');

    // 読み込み完了を待つ
    const primaryButtonText = await page.textContent('[data-testid="button-primary"]');
    expect(primaryButtonText).toBe('primary');

    // console.log('ページにアクセスしました。カバレッジを取得しています。');
    const coverage = await page.coverage.stopJSCoverage();
    for (const entry of coverage) {
        // entry.url からファイル名を抽出
        const fileName = entry.url.split('/').pop();
        const outCoverageFile = `${testInfo.outputDir}/Coverage_${fileName}.json`;

        const converter = v8ToIstanbul('', 0, { source: entry.source });

        await converter.load();
        converter.applyCoverage(entry.functions);

        const dir = testInfo.outputDir;
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(outCoverageFile, JSON.stringify(converter.toIstanbul(), null, 2));
        console.log(`カバレッジファイルを出力しました: ${outCoverageFile}`);



    }
    await browser.close();
});
*/