// Fetch関連の共通型定義と関数
//// リクエスト情報の型定義
export type ResourceObj<T> = {
    url: string;
    method?: "GET" | "POST" | "PUT" | "DELETE";
    body?: object | undefined;
    headers?: HeadersInit;
    takeData?: (response: Response) => Promise<T>;
};
// FetchコンポーネントのPropsの型定義
export type FetchComponentProps<T, U> = {
    resourceObj: ResourceObj<T>;
    renderSuccess?: ({ response }: { response: T }) => React.ReactElement;
    renderLoading?: () => React.ReactElement;
    renderError?: ({ error }: { error: U }) => React.ReactElement;
};

// FetchコンポーネントのPropsの型定義
//// リクエスト及び成功時レンダリングコンポーネント
export type SuccessProps<T> = {
    resourceObj: ResourceObj<T>;
    renderSuccess?: ({ response }: { response: T }) => React.ReactElement;
};

//// フォールバック用オブジェクト
export type FallBacksProps<U> = {
    renderLoading?: () => React.ReactElement;
    renderError?: ({ error }: { error: U }) => React.ReactElement;
}
//// リクエスト及び成功時のレンダリングを含むコンポーネント
export type FetchComponentProps<T, U> = SuccessProps<T> & FallBacksProps<U>;

