// Fetchコンポーネント
import React from 'react';
import { use, useState } from 'react';
// 共通型定義, フック, 関数読み込み
import { FetchComponentProps, SuccessProps } from './type';
import { requestFetch } from './common'
import { useFetchPromiseMemo } from './hook.ts';

// ErrorBoundary及びSuspenseのラッパーコンポーネント
import { W_ErrorBoundary, W_Suspense } from '../WrapperComponents';

//////// デフォルト表示コンポーネント ////////
//成功時デフォルト表示コンポーネント
const ShowSuccess = <T,>({ response }: { response: T }) => {
    console.log(response);
    return <>Success</>;
};
// ローディングデフォルト表示コンポーネント
const ShowLoading: React.FC = () => {
    console.log('loading...');
    return <>loading...</>;
};
// エラーデフォルト表示コンポーネント
const ShowError = <U,>({ error }: { error: U }) => {
    console.error(error);
    return <>Error.</>;
};

/**
 * Fetchリクエストを行い、結果を表示するコンポーネント
 * @param {string} uri APIのURI
 * @param {function} renderSuccess 成功時に表示するコンポーネント
 * @param {function} renderLoading ローディング時に表示するコンポーネント
 * @param {function} renderError エラー時に表示するコンポーネント
 * @returns {JSX.Element} 各状態でコンポーネント
 */
export const FetchComponent = <T, U>({
    resourceObj,
    renderSuccess = ShowSuccess,
    renderLoading = () => <ShowLoading />,
    renderError = ShowError,
    onError,
    onReset
}: FetchComponentProps<T, U>) => {
    // メモ化したFetchプロミスを取得
    const fetchPromise = useFetchPromiseMemo(resourceObj);
    // エラーバウンダリとサスペンスでラップレスポンス結果を表示
    return (
        <W_ErrorBoundary errorFallback={renderError} onError={onError} onReset={onReset}>
            <W_Suspense loadingFallback={renderLoading()}>
                <In_F<T> promise={fetchPromise} renderSuccess={renderSuccess} />
            </W_Suspense>
        </W_ErrorBoundary>
    );
};

// 内部コンポーネントのPropsの型定義
type In_F_Props<T> = { promise: Promise<T | null>; renderSuccess: ({ response }: { response: T }) => React.ReactElement; };
// use APIでプロミスの中身を取り出して扱うコンポーネント
const In_F = <T,>({ promise, renderSuccess }: In_F_Props<T>) => {
    console.log('In_F promise:', promise);
    const response = use(promise) as T;
    console.log('In_F response:', response);
    return (<>{renderSuccess({ response })}</>);
};

export default FetchComponent;
