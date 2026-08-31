/** 
 * 未認証ルートコンポーネント
 * 認証されていないユーザーがアクセスするルートを定義
*/
// ナビゲーションコンポーネント
import { Navigate } from "react-router-dom";

// 対象ページコンポーネント
import AuthLayout from '../pages/authentication';
import LoginPage from '../pages/authentication/login';

// エラーバウンダリーコンポーネント
import { W_ErrorBoundary_Router } from '@/utils/libs/WrapperComponents/ErrorBoundary';


// 未認証ルートの定義
const uncertifiedRoutes = [
    {
        id: 'auth:layout',
        path: '/',
        element: <AuthLayout />,
        ErrorBoundary: W_ErrorBoundary_Router,
        children: [
            { index: true, element: <Navigate to="login" replace /> },
            {
                id: 'auth:login',
                path: '/login',
                element: <LoginPage />,
            }
        ]
    },
    {
        id: 'auth:not-found',
        path: '*',
        element: <Navigate to="/login" replace />,
    }
];

export default uncertifiedRoutes;