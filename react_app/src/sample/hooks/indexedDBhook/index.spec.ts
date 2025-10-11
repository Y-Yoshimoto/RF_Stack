// indexedDBhookカスタムフックのテスト
import { describe, it, expect, vi, afterEach } from 'vitest';

// テスト対象の関数
import useIndexedDB from '.';
import { renderHook, waitFor } from "@testing-library/react"

describe('useIndexedDB', () => {
    // テスト用のデータ
    const baseTestData = { key: "testKey", data: { data: "baseTestData" } };
    const testConfig = {
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
        const { result } = renderHook(() => useIndexedDB({ config: testConfig }));
        return waitFor(() => {
            expect(result.current.isConnected).toBe(true);
            return result;
        }, { timeout: 100 });
    }

    afterEach(() => {
        // IndexedDBをクリアする
        const request = indexedDB.deleteDatabase(testConfig.db_name);
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
                result.current.upsertData(baseTestData.key, baseTestData.data);
                return result;
            })
            .then((result) => {
                return waitFor(() => {
                    // データを取得し確認する
                    result.current.getData(baseTestData.key, dispatcherMock);
                    expect(dispatcherMock).toHaveBeenCalledWith(baseTestData);
                    return result;
                }, { timeout: 100 });
            });
    });

});
