// useFetchカスタムフックのテスト
import { describe, it, expect, vi } from 'vitest';

// テスト対象の関数
import useFetch from '.';
import { renderHook, waitFor } from "@testing-library/react"

//// テストサンプル1 ////////////////////////////////////////

// fetchの成功を返す関数
// 参考: https://jestjs.io/ja/docs/mock-function-api#mockfnmockresolvedvaluevalue
type MockFetchParams = {
    bodyObj?: object;
    status?: number;
    statusText?: string;
};

const genMockFetch = ({ bodyObj = {}, status = 200, statusText = "" }: MockFetchParams) => {
    const body = JSON.stringify(bodyObj);
    return vi.spyOn(globalThis, 'fetch')
        .mockResolvedValue(new Response(body, { status, statusText }));
};
// fetchのエラーを返す関数(ネットワークエラー)
const genMockFetchError = (error: Error) => {
    return vi.spyOn(globalThis, 'fetch')
        .mockRejectedValue(error);
};

describe('Fetchモック動作確認', () => {
    it('サンプルテスト 200', async () => {
        const data = { message: 'Hello, World!' };
        const _ = genMockFetch({ bodyObj: data });
        const { result } = renderHook(() => useFetch<{ message: string }>({ url: './api/sample' }));
        await waitFor(() => {
            expect(result.current.response).toEqual(data);
            // console.log(result.current)
        });
    });

    it('サンプルテスト 200-Post', async () => {
        const data = { message: 'Hello, World!' };
        const _ = genMockFetch({ bodyObj: data, status: 200, statusText: 'OK' });
        const { result } = renderHook(() => useFetch<{ message: string }>({ url: './api/sample', method: 'POST', body: data }));
        await waitFor(() => {
            expect(result.current.response).toEqual(data);
            // console.log(result.current)
        });
    });

    it('サンプルテスト 404', async () => {
        const _ = genMockFetch({ bodyObj: { message: 'No Data' }, status: 404, statusText: 'Not Found' });
        const { result } = renderHook(() => useFetch<object>({ url: './api/sample' }));
        await waitFor(() => {
            //console.log(result.current.error);
            expect(result.current.error?.message).toEqual('Not Found');
            // console.log(result.current)
        });
    });

    it('サンプルテスト ネットワークエラー', async () => {
        const error = new Error('Network Error');
        const _ = genMockFetchError(error);
        const { result } = renderHook(() => useFetch<object>({ url: './api/sample' }));
        await waitFor(() => {
            expect(result.current.error?.message).toEqual('Network Error');
            // console.log(result.current)
        });
    });

});

//// テストサンプル2 ////////////////////////////////////////
// 複数回のfetchをモックする関数
// 参考: https://jestjs.io/ja/docs/mock-function-api#mockfnmockimplementationfn
const genMockFetches = (responseList: MockFetchParams[]) => {
    const generatorResponse = function* () {
        for (const response of responseList) {
            yield new Response(JSON.stringify(response.bodyObj), {
                status: response.status,
                statusText: response.statusText
            });
        };
    };
    // イテレータを生成
    const iterator = generatorResponse();
    // fetchのモックを生成
    return vi.spyOn(globalThis, 'fetch')
        .mockImplementation(() => Promise.resolve(iterator.next().value as Response));
}

// 複数回のfetchを行う場合のテスト
describe('Fetchモック動作確認', () => {

    // 200-200でレスポンスが返る場合, 2つのuseFetchを順番に呼び出す
    it('サンプルテスト 200-200', async () => {
        const response = [
            { bodyObj: { message: 'Data1' }, status: 200, statusText: 'OK' },
            { bodyObj: { message: 'Data2' }, status: 200, statusText: 'OK' }
        ];
        const _ = genMockFetches(response);
        // Fetch1回目
        const { result: result1 } = renderHook(() => useFetch<{ message: string }>({ url: './api/1' }));
        await waitFor(() => {
            expect(result1.current.response).toEqual(response[0].bodyObj);
        });
        const { result: result2 } = renderHook(() => useFetch<{ message: string }>({ url: './api/2' }));
        await waitFor(() => {
            expect(result2.current.response).toEqual(response[1].bodyObj);
        });
    });

    // 404-200でレスポンスが返る場合, 1つのuseFetchをURLを変えて2回呼び出す
    it('サンプルテスト 404-200', async () => {
        const response = [
            { bodyObj: { message: 'Nodata' }, status: 404, statusText: 'Not Found' },
            { bodyObj: { message: 'Data' }, status: 200, statusText: 'OK' }
        ];
        const _ = genMockFetches(response);
        // Fetch1回目
        const { result, rerender } = renderHook(
            ({ url }: { url: string }) => useFetch<{ message: string }>({ url }),
            { initialProps: { url: './api/9' } }
        );
        await waitFor(() => {
            // console.log(result.current);
            expect(result.current.error?.message).toEqual('Not Found');
        });
        // Fetch2回目
        rerender({ url: './api/1' });
        await waitFor(() => {
            // console.log(result.current);
            expect(result.current.response).toEqual(response[1].bodyObj);
            expect(result.current.error).toBeNull();
        });
    });
});
