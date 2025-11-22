// Fetchコンポーネント
import React from 'react';
import useFetch from '../fetchhook';
import { T } from 'vitest/dist/chunks/reporters.d.BFLkQcL6.js';

// FetchコンポーネントのPropsの型定義
type FetchComponentProps<T, U> = {
  url: string;
  renderSuccess?: ({ response }: { response: T }) => React.ReactElement;
  renderLoading?: () => React.ReactElement;
  renderError?: ({ error }: { error: U }) => React.ReactElement;
};

/**
 * Fetchリクエストを行い、結果を表示するコンポーネント
 * @param {string} url APIのURL
 * @param {function} renderSuccess 成功時に表示するコンポーネント
 * @param {function} renderLoading ローディング時に表示するコンポーネント
 * @param {function} renderError エラー時に表示するコンポーネント
 * @returns {JSX.Element} 各状態でコンポーネント
 */
export const FetchComponent = <T, U>({
  url,
  renderSuccess = ({ response }: { response: T }) => <ShowSuccess response={response} />,
  renderLoading = () => <ShowLoading />,
  renderError = ({ error }: { error: U }) => <ShowError error={error} />,
}: FetchComponentProps<T, U>) => {
  const { response, loading, error } = useFetch({ url });
  if (loading) return renderLoading();
  if (error) return renderError({ error: error as U });
  if (response) return renderSuccess({ response: response as T });
  return null;
};

//成功表示デフォルトコンポーネント
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

export default FetchComponent;
