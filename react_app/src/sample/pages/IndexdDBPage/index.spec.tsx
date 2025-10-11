// IndexedDBPageのテスト
import { expect, describe, it } from 'vitest';

import '@testing-library/jest-dom';
import { render, fireEvent, act, waitFor } from '@testing-library/react';

// テスト対象
import { IndexedDBSampleComponent } from './index';

describe('IndexedDBPageのテスト', () => {

    // IndexedDBと接続されてタイトルが表示されることを確認
    const waitConnected = async (page) => {
        return waitFor(() => {
            expect(page.getByText('IndexedDB Component')).toBeInTheDocument();
        }, { timeout: 100 });
    }

    const testMehthod_addDeta = async (page, setKey: string) => {
        // キー入力フィールドの取得
        const keyInput = page.getByTestId('set-key-input').querySelector('input');
        // キー入力が存在することを確認して値を設定
        await act(async () => {
            if (!keyInput) throw new Error('Key input not found');
            fireEvent.change(keyInput, { target: { value: setKey } });
        });
        // データ登録ボタンをクリック
        fireEvent.click(page.getByRole('button', { name: 'Add Data' }));
    };


    it('初期表示の確認', async () => {
        const page = render(<IndexedDBSampleComponent />);
        await waitFor(() => {
            // IndexedDBと接続されてタイトルが表示されることを確認
            expect(page.getByText('IndexedDB Component')).toBeInTheDocument();
        }, { timeout: 100 });
        // ボタンの表示確認
        expect(page.getByRole('button', { name: 'Add Data' })).toBeInTheDocument();
        expect(page.getByRole('button', { name: 'Get' })).toBeInTheDocument();
        expect(page.getByRole('button', { name: 'Get All' })).toBeInTheDocument();
        expect(page.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
        expect(page.getByRole('button', { name: 'Clear All' })).toBeInTheDocument();
        // テキストフィールドの表示確認
        expect(page.getByTestId('set-key-input')).toBeInTheDocument();
        // 初期表示のテキスト確認
        expect(page.getByText('IndexedDB Component')).toBeInTheDocument();
        expect(page.getByText(/登録用データ:/)).toBeInTheDocument();
        expect(page.getByText(/取得データ/)).toBeInTheDocument();
        // 初期表示のデータが空であることを確認
        expect(page.getByTestId('response-info')).toHaveTextContent('undefined');
        // 入力フィールドの表示確認
        expect(page.getByTestId('set-key-input')).toBeInTheDocument();
    });

    it('データの登録と取得のテスト', async () => {
        const page = render(<IndexedDBSampleComponent />);
        await waitConnected(page);

        // データ登録
        await testMehthod_addDeta(page, 'testKey');
        // データ取得ボタンをクリック
        fireEvent.click(page.getByRole('button', { name: 'Get' }));
        // 取得したデータの確認
        await waitFor(() => {
            expect(page.getByTestId('response-info')).toHaveTextContent('testKey');
        }, { timeout: 10 });
    });

});