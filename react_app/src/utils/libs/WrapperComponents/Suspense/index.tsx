// 読み込み表示用のSuspense
import { ReactNode } from 'react';
import { Suspense } from 'react';

export type SuspenseProps = {
    children: ReactNode; // Suspenseがラップする子コンポーネント
    loading_fallback?: ReactNode; // 読み込み中に表示するコンポーネント
};

export const LoadingDefault = () => {
    return <div>Loading...</div>;
};

export const WSuspense = ({ children, loading_fallback = <LoadingDefault /> }: SuspenseProps) => {
    return (
        <Suspense fallback={loading_fallback}>
            {children}
        </Suspense>
    );
};

export default WSuspense;