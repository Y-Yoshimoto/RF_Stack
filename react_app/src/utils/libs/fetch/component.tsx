// Fetchコンポーネント
import React from 'react';
import { use } from 'react';
import useFetch from './hook.ts';
// 共通型定義読み込み
import { ResourceObj, requestFetch } from './common'
import { T } from 'vitest/dist/chunks/reporters.d.BFLkQcL6.js';

// FetchコンポーネントのPropsの型定義
//// リクエスト及び成功時レンダリングコンポーネント
type SuccessProps<T> = {
    resourceObj: ResourceObj<T>;
    renderSuccess?: ({ response }: { response: T }) => React.ReactElement;
};

//// フォールバック用オブジェクト
type FallBacksProps<U> = {
    renderLoading?: () => React.ReactElement;
    renderError?: ({ error }: { error: U }) => React.ReactElement;
}
//// リクエスト及び成功時のレンダリングを含むコンポーネント
type FetchComponentProps<T, U> = SuccessProps<T> & FallBacksProps<U>;

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
    // renderSuccess = ({ response }: { response: T }) => <ShowSuccess response={response} />,
    renderLoading = () => <ShowLoading />,
    renderError = ({ error }: { error: U }) => <ShowError error={error} />,
}: FetchComponentProps<T, U>) => {
    const { response, loading, error } = useFetch(resourceObj);
    if (loading) return renderLoading();
    if (error) return renderError({ error: error as U });
    if (response) return renderSuccess({ response: response as T });
    return null;
};


/* Fetch-useAPIコンポーネント
 * use APIを使用して、プロミスを受け取ってレスポンスを扱うコンポーネント
 * PromiseWrapper又は、Suspense, ErrorBoundaryでラップして使用する
*/
export const FetchComponentUseAPI = ({ resourceObj, renderSuccess = ShowSuccess }: SuccessProps<T>) => {
    return (<In_FetchComponentUseAPI promise={requestFetch(resourceObj)} renderSuccess={renderSuccess} />);
};
// 内部コンポーネントのPropsの型定義
type In_FetchComponentUseAPIProps<T> = {
    promise: Promise<T | null>;
    renderSuccess: ({ response }: { response: T }) => React.ReactElement;
}
// use APIでプロミスの中身を取り出して扱うコンポーネント
const In_FetchComponentUseAPI = ({ promise, renderSuccess }: In_FetchComponentUseAPIProps<T>) => {
    const data = use(promise) as T;
    return (<>{renderSuccess({ response: data })}</>);
};

export default FetchComponent;
