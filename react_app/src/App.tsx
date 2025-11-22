// ルーター読み込み
import { AppRoutes } from './routes';
// 読み込み表示用のSuspense
import { Suspense } from 'react';

// 全体のエラーバウンダリー
import W_ErrorBoundary from '@/utils/WrapperComponent/ErrorBoundary';

// MUIのテーマプロバイダー
import { ThemeProvider } from '@mui/material/styles';
import theme from './theme.tsx';

// APPコンポーネント
// アプリケーション全体へのサスペンドとエラーバウンダリー, テーマプロバイダーを設定
export default function App() {
  return (
    <Suspense fallback={<></>}>
      <W_ErrorBoundary>
        <ThemeProvider theme={theme}>
          <AppRoutes />
        </ThemeProvider>
      </W_ErrorBoundary>
    </Suspense>
  );
}
