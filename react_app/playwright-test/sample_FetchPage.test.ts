import { test, expect } from '@playwright/test';


test.describe('FetchPageのテスト', () => {
    test('初期と2回目の表示を確認する', async ({ page }: { page }) => {
        // Fetchのモックを生成
        await page.route('**/static.json?key=*', (route) => {
            route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ id: 1, type: 'static', name: 'data' }),
            });
        });
        // FetchPageを開く
        await page.goto('/fetch');
        // 全てのボタンのテキストを取得
        const [requestButton] = await Promise.all([
            page.getByTestId('request-button'), page.getByText('Fetch Component'),
        ]);
        // レスポンスの表示を確認する
        const responseInfo = await page.getByTestId('response-info');
        await expect(responseInfo).toBeVisible();
        // リクエストボタンをクリックする
        await requestButton.click();
        await expect(responseInfo).toBeVisible();

    });
});
