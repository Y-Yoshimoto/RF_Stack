// 読み込み表示用のSuspense
import { ReactNode } from 'react';
import { Suspense } from 'react';

export type SuspenseProps = {
    children: ReactNode; // Suspenseがラップする子コンポーネント
    loadingFallback?: ReactNode; // 読み込み中に表示するコンポーネント
};

export const Loading_default = () => {
    return <div>Loading...</div>;
};

export const W_Suspense = ({ children, loadingFallback = <Loading_default /> }: SuspenseProps) => {
    return (
        <Suspense fallback={loadingFallback}>
            {children}
        </Suspense>
    );
};

export default W_Suspense;