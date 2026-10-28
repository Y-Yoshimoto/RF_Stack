/**
 * @desc サンプル画面のルート (`/{tenant_code}/sample/*`。AP の認証後画面として扱う)
 * 基盤の実装が進んだ段階で sample/ ごと削除する (02 §6.1)。
 * AP のルート (main_app/routes.tsx) から遅延読み込みされる。
 * 旧ルートのうち、ローダー (データルーター) を前提とする fetch-loader と、旧ログアウト画面 (/logout) は削除した。
 */
import { Route, Routes } from 'react-router-dom';
import ButtonPage from '@/sample/pages/ButtonPage';
import ErrorPage from '@/sample/pages/ErrorPage';
import FetchPage from '@/sample/pages/FetchPage';
import FetchUse from '@/sample/pages/FetchPage/FetchUse';
import IndexedDBPage from '@/sample/pages/IndexdDBPage';
import LeyoutChildren from '@/sample/pages/LeyoutChildren';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { WErrorBoundary } from '@/utils/libs/WrapperComponents/ErrorBoundary';

// パスの名前は sample/sample_names.ts の SAMPLE_NAMES と揃える

export const SampleRoutes = () => {
    return (
        <Routes>
            <Route path="button" element={<ButtonPage />} />
            <Route path="fetch" element={<FetchPage />} />
            <Route path="fetch-use" element={<FetchUse />} />
            <Route path="indexedDB" element={<IndexedDBPage />} />
            <Route path="layoutChildren" element={<LeyoutChildren />} />
            {/* 子孫ルートでは route の ErrorBoundary が使えないため、要素をエラーバウンダリーで包む */}
            <Route path="error" element={<WErrorBoundary><ErrorPage /></WErrorBoundary>} />
            {/* AP のレイアウト (<main> を持つ) の中に表示されるため embedded */}
            <Route path="*" element={<NotFoundPage embedded />} />
        </Routes>
    );
};

export default SampleRoutes;
