// indexedDBhookカスタムフックのテスト
import { describe, it, expect, vi, afterEach } from 'vitest';

// テスト対象の関数
import useIndexedDB from '.';
import { renderHook, waitFor } from "@testing-library/react"

describe('useIndexedDB', () => {
    // テスト用のデータ
    const base_test_data = { key: "testKey", data: { data: "base_test_data" } };
    const test_config = {
        db_name: "testDB",
        db_version: 1,
        objectStore_name: "cache",
        keyPath: "key"
    };
    // テスト用のモック関数
    const dispatcherMock = vi.fn();
    // テスト用のフックを含むプロミスを返す関数
    // 解決すると、resultを返すプロミスが返されるため、.then()で使用できる
    const dBHookPromise = async () => {
        const { result } = renderHook(() => useIndexedDB({ config: test_config }));
        return waitFor(() => {
            expect(result.current.isConnected).toBe(true);
            return result;
        }, { timeout: 100 });
    }

    afterEach(() => {
        // IndexedDBをクリアする
        const request = indexedDB.deleteDatabase(test_config.db_name);
        request.onsuccess = () => {
            console.log("Database deleted successfully");
        };
        request.onerror = () => {
            console.error("Error deleting database");
        };
        // モック関数をクリアする
        return dispatcherMock.mockClear();
    });

    it('データ登録と取得1', () => {
        return dBHookPromise()
            .then((result) => {
                // データを追加する
                result.current.upsertData(base_test_data.key, base_test_data.data);
                return result;
            })
            .then((result) => {
                return waitFor(() => {
                    // データを取得し確認する
                    result.current.getData(base_test_data.key, dispatcherMock);
                    expect(dispatcherMock).toHaveBeenCalledWith(base_test_data);
                    return result;
                }, { timeout: 100 });
            });
    });

});
