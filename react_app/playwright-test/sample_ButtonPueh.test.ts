import { test, expect } from '@playwright/test';

test.describe('ButtonPueh', () => {
    test('ボタンのテキストを確認する', async ({ page }: { page }) => {
        await page.goto('/button');
        // 全てのボタンのテキストを取得
        const [primaryButtonText, secondaryButtonText, clearButtonText] = await Promise.all([
            page.textContent('[data-testid="button-primary"]'),
            page.textContent('[data-testid="button-secondary"]'),
            page.textContent('[data-testid="button-clear"]')
        ]);
        expect(primaryButtonText).toBe('primary');
        expect(secondaryButtonText).toBe('secondary');
        expect(clearButtonText).toBe('clear');
    });

    test('ボタンをクリックしてテキストを変更する', async ({ page }: { page }) => {
        await page.goto('/button');
        // data-testid="button-primary"のボタンをクリックする
        await page.getByTestId('button-primary').click();

        // data-testid="text-label"のテキストがprimaryであることを確認
        await page.textContent('[data-testid="text-label"]').then((textLabel) => {
            expect(textLabel).toBe('primary');
        });
    });


    test('プロミス内でテスト実施する', async ({ page }: { page }) => {
        return page.goto('/button').then(() => {
            const actionCallback = () => clickButton(page, '[data-testid="button-secondary"]');
            const expextCallback = () => expectCheckText(page, '[data-testid="text-label"]', 'secondary');
            return testSet(actionCallback, expextCallback);
        });
    });

    // テキストの内容を確認する
    const expectCheckText = (page, textSelector: string, expectedText: string) => {
        return page.textContent(textSelector).then(text => expect(text).toBe(expectedText));
    };

    // ボタンをクリックして期待結果を確認する
    const clickButton = (page, buttonSelector: string) => page.click(buttonSelector);
    // テスト実施
    const testSet = (actionCallback: () => Promise<void>, expextCallback: () => Promise<void>) => {
        return actionCallback().then(() => expextCallback());
    };
});