import { FetchSampleComponent } from './index';
import { render, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import '@testing-library/jest-dom';
import { act } from 'react';
// テスト用のJSONデータ

describe('ページユニットテスト', () => {
    // fetchモック
    const genMockFetch = ({ bodyObj = {}, status = 200, statusText = '' }) => {
        const body = JSON.stringify(bodyObj);
        const genResponse = () => (new Response(body, { status, statusText }));
        return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => genResponse());
    };
    // テスト用のサンプルデータ
    const sampleData = { id: 1, type: 'static', name: 'data', };

    it('Fetchコンポーネント1', async () => {
        // モックのFetchを生成
        const _mockFetch1 = genMockFetch({ bodyObj: sampleData, status: 200, statusText: 'OK' });
        // コンポーネントをレンダリング
        const { getByTestId, queryByTestId } = render(<FetchSampleComponent />);

        // requestボタンを取得
        const requestButton = queryByTestId('request-button');
        // ボタンが存在することを確認
        expect(requestButton).toBeInTheDocument();
        // ボタンのテキストを確認
        await waitFor(() => { expect(getByTestId('response-info')).toBeInTheDocument(); });
        // ボタンをクリック
        act(() => { fireEvent.click(requestButton!); });
        // データ表示箇所が再度表示されることを確認
        await waitFor(() => { expect(getByTestId('response-info')).toBeInTheDocument(); });

        // プロミスでテストを実施する
        await waitFor(() => {
            expect(getByTestId('response-info')).toBeInTheDocument();
        }).then(() => act(() => fireEvent.click(getByTestId('request-button')))
        ).then(() => {
            return waitFor(() => {
                expect(getByTestId('response-info')).toBeInTheDocument();
            })
        });
    });

    // ToDo: waitFor, act, expectを順番に実行するようなリストでテストを書けるようにする。
    it('Fetchコンポーネントテスト2', async () => {
        // モックのFetchを生成
        const _mockFetch1 = genMockFetch({ bodyObj: sampleData, status: 200, statusText: 'OK' });
        // コンポーネントをレンダリング
        // const { getByTestId, queryByTestId } = render(<FetchSampleComponent />);
        // requestボタンを取得
        // const requestButton = queryByTestId('request-button');

    });
});
