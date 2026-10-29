import { test, expect } from '@playwright/test';

test('ページタイトル取得', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('Vite App');
});
