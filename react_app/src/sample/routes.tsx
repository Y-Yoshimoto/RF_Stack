/**
 * @desc サンプル画面のルート (参考用。アプリに登録していない)
 * src/sample/ はアプリのルーティングに登録していない参考用のコードである (02 §6.1)。どこからも読み込まれず、バンドルにも含まれない。
 * 呼び出し先の FastAPI のサンプル API (/RestSample/*、/sample/todos、/api/demo/login) もアプリへの登録を外しているため、それらを呼ぶ画面は動かない。
 * lint・型チェック・vitest の対象には残すため、壊さないよう保守する。
 * 登録していた頃は AP のルート (main_app/routes.tsx) の `sample/*` (`/{tenant_code}/sample/*`) から遅延読み込みしていた。
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
