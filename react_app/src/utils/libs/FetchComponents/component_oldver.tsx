// 旧版Fetchコンポーネント
// カバレッジ無効化
/* istanbul ignore file */

// Fetchコンポーネント
import React from 'react';
import { use, useState } from 'react';
import useFetch from './hook.ts';
// 共通型定義読み込み
import { FetchComponentProps, SuccessProps } from './type';
// 共通関数読み込み
import { requestFetch } from './common'

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
export const FetchComponentClassic = <T, U>({
    resource_obj,
    renderSuccess = ShowSuccess,
    // renderSuccess = ({ response }: { response: T }) => <ShowSuccess response={response} />,
    renderLoading = () => <ShowLoading />,
    renderError = ({ error }: { error: U }) => <ShowError error={error} />,
}: FetchComponentProps<T, U>) => {
    const { response, loading, error } = useFetch(resource_obj);
    if (loading) return renderLoading();
    if (error) return renderError({ error: error as U });
    if (response) return renderSuccess({ response: response as T });
    return null;
};

/* Fetch-useAPIコンポーネント
 * use APIを使用して、プロミスを受け取ってレスポンスを扱うコンポーネント
 * PromiseWrapper又は、Suspense, ErrorBoundaryでラップして使用する
*/
export const FetchComponentAPI = ({ resource_obj, renderSuccess = ShowSuccess }: SuccessProps<T>) => {
    const [fetch_promise,] = useState(requestFetch(resource_obj));

    return (<InFetchComponentUseAPI promise={fetch_promise} renderSuccess={renderSuccess} />);
};
// 内部コンポーネントのPropsの型定義
type InFetchComponentUseAPIProps<T> = {
    promise: Promise<T | null>;
    renderSuccess: ({ response }: { response: T }) => React.ReactElement;
}
// use APIでプロミスの中身を取り出して扱うコンポーネント
const InFetchComponentUseAPI = ({ promise, renderSuccess }: InFetchComponentUseAPIProps<T>) => {
    const data = use(promise) as T;
    return (<>{renderSuccess({ response: data })}</>);
};

export default FetchComponentClassic;
