/**
 * IndexedDBを使用してデータを保存するカスタムフック
 * @description
 * - IndexedDBのデータベース名、バージョン、オブジェクトストア名を定義
 * https://developer.mozilla.org/ja/docs/Web/API/IndexedDB_API
 */
/* eslint-disable */
import { useState, useEffect, useMemo, useRef } from 'react';

// データベースの接続先
//// IndexedDBのデータベース名、バージョン、オブジェクトストア名, キーを定義
const DB_NAME = "testDB";
const DB_VERSION = 1;
const OBJECTSTPRE_NAME = "cache";
const DB_KEYPATH = "key";

// 型定義
type requestType = {
    requestKey?: string;
    period?: number;
};
type configType = {
    db_name: string;
    db_version: number;
    objectStore_name: string;
    keyPath: string;
};
type propsType = {
    period?: number;
    config?: configType;
};
// IndexedDBのデフォルト接続先情報
const defaultConfig: configType = {
    db_name: DB_NAME,
    db_version: DB_VERSION,
    objectStore_name: OBJECTSTPRE_NAME,
    keyPath: DB_KEYPATH
};


// IndexedDBにデータを保存するカスタムフック
export const useIndexedDB = <T>({ period = 100, config = defaultConfig }: propsType) => {
    // 静的なプロパティを分割する
    const { db_name, db_version, objectStore_name, keyPath } = config;
    const [conDB, setConDB] = useState<IDBDatabase | null>(null);


    // リクエストオブジェクトメモを生成
    const requestDB = useMemo(() => {
        // console.log(`useIndexedDB: ${db_name}, ${db_version}`);
        const request = window.indexedDB.open(db_name, db_version);
        // 成功/エラー時の処理
        request.onsuccess = (event) => {
            // DB接続をステートに保存
            const db = (event.target as IDBOpenDBRequest).result as IDBDatabase;
            setConDB(db);
        };
        request.onerror = (event) => { console.error("IndexedDB error: ", event); };
        // データベースの名前, バージョンが変更されたときの処理(トランザクションオブジェクトを返す)
        request.onupgradeneeded = (event) => {
            const db = (event.target as IDBOpenDBRequest).result as IDBDatabase;
            return db.createObjectStore(objectStore_name, { keyPath: keyPath });
        };
        return request; // リクエストオブジェクトを返す
    }, [db_name, db_version]);

    const openObjectStore = (mode: "readonly" | "readwrite" | "versionchange") => {
        // const transaction = requestDB.result?.transaction(objectStore_name, mode);
        const transaction = conDB?.transaction(objectStore_name, mode);
        const objectStore = transaction?.objectStore(objectStore_name);
        // 処理が完了したときの処理
        if (!transaction) throw new Error("Transaction is not defined");
        transaction.oncomplete = (event) => {
            // console.debug("transaction oncomplete: ", event)
        };
        // エラーが発生した時の処理
        transaction.onerror = (event) => { console.error("transaction onerror: ", event) };
        return objectStore;
    };

    // オブジェクトストアを使用した操作メソッド
    // https://developer.mozilla.org/ja/docs/Web/API/IDBObjectStore

    // データ追加, 更新
    // overwrite: trueの場合はput, falseの場合はadd
    // put: 既存のデータを上書きする
    // add: 新しいデータを追加する(既存のデータは上書きしない)
    const upsertData = (key: string, data: any, overwrite = true) => {
        const objectStore = openObjectStore("readwrite");
        if (overwrite) return objectStore?.put({ key, data });
        else return objectStore?.add({ key, data });
    };
    // データ削除
    const deleteData = (key: string) => {
        return openObjectStore("readwrite")?.delete(key);
    };
    // データ取得
    const getData = <T>(key: string, dispatcher: (data: T) => void) => {
        const req = openObjectStore("readonly")?.get(key);
        if (!req) throw new Error("Object store is not defined");
        req.onsuccess = ({ target }) => { dispatcher((target as IDBRequest).result); };
        return req;
    };
    // データクリア
    const clearData = () => {
        return openObjectStore("readwrite")?.clear();
    };
    // 全てのデータを取得
    const getAllData = (dispatcher: (data: any) => void) => {
        const request = openObjectStore("readonly")?.getAll();
        if (!request) throw new Error("Object store is not defined");
        request.onsuccess = (e) => { dispatcher((e.target as IDBRequest).result); };
        return request;
    };

    // DB接続が完了したかどうかを確認するフラグ
    const isConnected = (conDB !== null && requestDB.readyState === 'done');

    return { upsertData, deleteData, getData, clearData, getAllData, isConnected };
};

export default useIndexedDB;