/**
 * エラー境界コンポーネント
 * ユニットテスト用
 */
import { vi, expect, describe, it, beforeEach, beforeAll, afterAll } from 'vitest';
import '@testing-library/jest-dom';
import { screen, render, fireEvent, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event'
// テスト対象
import { W_ErrorBoundary, W_ErrorBoundary_Router, onReset_default } from "./"

// テスト用に意図的にエラーを発生させるコンポーネント
const Test_ErrorPage = () => {
    // 意図的なエラーを発生させる
    console.warn("意図的なエラーを発生させます。")
    throw new Error("テスト用エラー");

    return (
        <>
            <h1>内部エラーが発生しました</h1>
        </>
    );
};


describe('エラーバウンダリーテスト', () => {
    // vi.spyOn(window.location, 'reload')

    it('エラーバウンダリーがフォールバックUIを表示すること', async () => {
        const { getAllByText } = render(<W_ErrorBoundary><Test_ErrorPage /></W_ErrorBoundary>);
        console.log("#####################################");
        await waitFor(() => {
            const errorElements = getAllByText(/テスト用エラー/);
            expect(errorElements.length).toBeGreaterThanOrEqual(2);
        }, { timeout: 1000, interval: 10 });
    });

    it('エラーバウンダリーのフォールバックUIの再読み込みボタンが動作すること', () => {
        const user = userEvent.setup()
        const reload_mock = vi.fn(() => 0);
        const onReset = onReset_default(reload_mock);
        const { getByRole } = render(<W_ErrorBoundary onReset={onReset}><Test_ErrorPage /></W_ErrorBoundary>);
        const reloadButton = getByRole('button', { name: /再読み込み/i });
        // アクション後のプロミスの中で評価する
        return user.click(reloadButton).then(() => {
            expect(reload_mock).toHaveBeenCalled();
        });
    });
});