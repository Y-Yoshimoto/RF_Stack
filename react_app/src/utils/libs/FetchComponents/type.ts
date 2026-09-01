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
    resource_obj: ResourceObj<T>;
    renderSuccess?: ({ response }: { response: T }) => React.ReactElement;
    renderLoading?: () => React.ReactElement;
    renderError?: ({ error }: { error: U }) => React.ReactElement;
    onError?: (error: Error, info: React.ErrorInfo, isSendError: boolean) => void;
    onReset?: () => void;
};

// FetchコンポーネントのPropsの型定義
//// リクエスト及び成功時レンダリングコンポーネント
export type SuccessProps<T> = {
    resource_obj: ResourceObj<T>;
    renderSuccess?: ({ response }: { response: T }) => React.ReactElement;
};

//// フォールバック用オブジェクト
export type FallBacksProps<U> = {
    renderLoading?: () => React.ReactElement;
    renderError?: ({ error }: { error: U }) => React.ReactElement;
}

