import W_ErrorBoundary from '@/utils/wrapper/ErrorBoundary';

// エラーを表示するためのサンプルページ
const ErrorPage = () => {
    return (
        <W_ErrorBoundary>
            <ErrorPage_Internal />
        </W_ErrorBoundary>
    );
};
export default ErrorPage;

const ErrorPage_Internal = () => {
    // 意図的なエラーを発生させる
    console.warn("意図的なエラーを発生させます。")
    throw new Error("意図的なエラー");

    return (
        <>
            <h1>内部エラーが発生しました</h1>
        </>
    );
};