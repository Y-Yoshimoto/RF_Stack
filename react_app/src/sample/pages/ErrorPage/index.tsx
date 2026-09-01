import WErrorBoundary from '@/utils/libs/WrapperComponents/ErrorBoundary';

// エラーを表示するためのサンプルページ
const ErrorPage = () => {
    return (
        <WErrorBoundary>
            <ErrorPageInternal />
        </WErrorBoundary>
    );
};
export default ErrorPage;

const ErrorPageInternal = () => {
    // 意図的なエラーを発生させる
    console.warn("意図的なエラーを発生させます。")
    throw new Error("意図的なエラー");

    return (
        <>
            <h1>内部エラーが発生しました</h1>
        </>
    );
};