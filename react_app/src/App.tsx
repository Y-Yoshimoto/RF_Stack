// ルーター読み込み
import { AppRoutes } from './routes';
// 読み込み表示用のSuspense
import { Suspense } from 'react';

// 全体のエラーバウンダリー
import WErrorBoundary from '@/utils/libs/WrapperComponents/ErrorBoundary';

// MUIのテーマプロバイダー
import { ThemeProvider } from '@mui/material/styles';
import theme from './theme.tsx';

// APPコンポーネント
// アプリケーション全体へのサスペンドとエラーバウンダリー, テーマプロバイダーを設定
export default function App() {
  return (
    <Suspense fallback={<></>}>
      <WErrorBoundary>
        <ThemeProvider theme={theme}>
          <AppRoutes />
        </ThemeProvider>
      </WErrorBoundary>
    </Suspense>
  );
}
