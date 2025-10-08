import { test, expect } from '@playwright/test';

test.describe('Playwright実行環境チェック', () => {
    test('ブラウザが利用可能であること', async ({ browserName }) => {
        expect(['chromium', 'firefox', 'webkit']).toContain(browserName);
    });
});