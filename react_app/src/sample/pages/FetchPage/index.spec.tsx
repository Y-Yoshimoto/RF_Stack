import { Suspense } from 'react';

import { FetchSampleComponent } from './index';
import { render, fireEvent, waitFor, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import '@testing-library/jest-dom';
import { act } from 'react';
// テスト用のJSONデータ

describe('ページユニットテスト', () => {
    // fetchモック
    const genMockFetch = ({ bodyObj = {}, status = 200, statusText = '' }) => {
        const body = JSON.stringify(bodyObj);
        const genResponse = () => (new Response(body, { status, statusText }));
        // 次tickで解決するようにして React の更新タイミングと合うようにする
        return vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
            new Promise((resolve) => setTimeout(() => resolve(genResponse()), 0))
        );
        // return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => genResponse());
    };
    // テスト用のサンプルデータ
    const sampleData = { id: 1, type: 'static', name: 'data', };

    it('Fetchコンポーネント1', async () => {
        // モックのFetchを生成
        const _mockFetch1 = genMockFetch({ bodyObj: sampleData, status: 200, statusText: 'OK' });
        // コンポーネントをレンダリング
        // render を act でラップして await する
        await act(async () => {
            render(
                <Suspense fallback={<div>loading...</div>}>
                    <FetchSampleComponent />
                </Suspense>
            );
            // microtask をフラッシュするために最低1回 await
            await Promise.resolve();
        });

        // ボタンが存在することを確認
        await waitFor(() => {
            const requestButton = screen.queryByTestId('request-button');
            expect(requestButton).toBeInTheDocument();
            expect(requestButton).toHaveTextContent('Request')
        }, { timeout: 1000 })

        await waitFor(() => {
            expect(screen.getByTestId('response-info')).toBeInTheDocument();
            screen.debug();
        });
        // ボタンのテキストを確認
        await waitFor(() => {
            expect(screen.getByTestId('response-info')).toBeInTheDocument();
            screen.debug();
        }, { timeout: 1000 });
        // ボタンをクリック
        const requestButton = screen.queryByTestId('request-button');
        await act(() => { fireEvent.click(requestButton!); });
        // データ表示箇所が再度表示されることを確認
        await waitFor(() => { expect(screen.getByTestId('response-info')).toBeInTheDocument(); }, { timeout: 1000 });

        // プロミスでテストを実施する
        await waitFor(() => {
            expect(screen.getByTestId('response-info')).toBeInTheDocument();
        }).then(() => act(() => fireEvent.click(screen.getByTestId('request-button')))
        ).then(() => {
            return waitFor(() => {
                expect(screen.getByTestId('response-info')).toBeInTheDocument();
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
