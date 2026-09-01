/**
 * エラー境界コンポーネント
 * ユニットテスト用
 */
import { vi, expect, describe, it, beforeEach, beforeAll, afterAll } from 'vitest';
import '@testing-library/jest-dom';
import { screen, render, fireEvent, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event'
// テスト対象
import { WErrorBoundary, WErrorBoundaryRouter, onResetDefault } from "./"

// テスト用に意図的にエラーを発生させるコンポーネント
const TestErrorPage = () => {
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
        const { getAllByText } = render(<WErrorBoundary><TestErrorPage /></WErrorBoundary>);
        console.log("#####################################");
        await waitFor(() => {
            const error_elements = getAllByText(/テスト用エラー/);
            expect(error_elements.length).toBeGreaterThanOrEqual(2);
        }, { timeout: 1000, interval: 10 });
    });

    it('エラーバウンダリーのフォールバックUIの再読み込みボタンが動作すること', () => {
        const user = userEvent.setup()
        const reloadMock = vi.fn(() => 0);
        const on_reset = onResetDefault(reloadMock);
        const { getByRole } = render(<WErrorBoundary onReset={on_reset}><TestErrorPage /></WErrorBoundary>);
        const reload_button = getByRole('button', { name: /再読み込み/i });
        // アクション後のプロミスの中で評価する
        return user.click(reload_button).then(() => {
            expect(reloadMock).toHaveBeenCalled();
        });
    });
});