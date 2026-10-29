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
// アプリケーション全体へのサスペンドとエラーバウンダリー, テーマプロバイダーを提供する。
// 認証状態はプレーン毎に別インスタンスとし、各プレーンのルートツリーの中で提供する
// (main_app/auth/AppAuthProvider、control_plane_app/auth/ControlPlaneAuthProvider。01 §11.2)。
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
