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
const Test_ErrorPage = () => { throw new Error("テスト用エラー"); };

describe('エラーバウンダリーテスト', () => {
    // vi.spyOn(window.location, 'reload')

    it('エラーバウンダリーがフォールバックUIを表示すること', () => {
        const { getByText } = render(<W_ErrorBoundary><Test_ErrorPage /></W_ErrorBoundary>);
        expect(getByText('テスト用エラー')).toBeInTheDocument();
    });

    it('エラーバウンダリーのフォールバックUIの再読み込みボタンが動作すること', async () => {
        const user = userEvent.setup()
        const reload_mock = vi.fn(() => 0);
        const onReset = onReset_default(reload_mock);

        const { getByText, getByRole } = render(<W_ErrorBoundary onReset={onReset}><Test_ErrorPage /></W_ErrorBoundary>);
        const reloadButton = getByRole('button', { name: /再読み込み/i });
        // アクション後のプロミスの中で評価する
        await user.click(reloadButton).then(() => {
            // expect(getByText('テスト用エラー')).toBeInTheDocument();
            expect(reload_mock).toHaveBeenCalled();
        });

    });
});