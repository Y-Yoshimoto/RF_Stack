// ルーター読み込み
import { AppRoutes } from './routes';
// 読み込み表示用のSuspense
import { Suspense } from 'react';

// 全体のエラーバウンダリー
import W_ErrorBoundary from '@/utils/libs/WrapperComponents/ErrorBoundary';

// MUIのテーマプロバイダー
import { ThemeProvider } from '@mui/material/styles';
import theme from './theme.tsx';

// 認証認可コンテキストプロバイダー
import { AuthNZProvider } from './store/AuthNZ/index.tsx';


// APPコンポーネント
// アプリケーション全体へのサスペンドとエラーバウンダリー, テーマプロバイダー、認証認可プロバイダーを提供
export default function App() {

  return (
    <Suspense fallback={<></>}>
      <W_ErrorBoundary>
        <ThemeProvider theme={theme}>
          <AuthNZProvider>
            <AppRoutes />
          </AuthNZProvider>
        </ThemeProvider>
      </W_ErrorBoundary>
    </Suspense>
  );
}
