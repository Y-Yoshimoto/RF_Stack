import React from 'react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
// StrictMode使用可否環境変数の取得とコンポーネント生成
const VITE_ENABLE_STRICTMODE = JSON.parse(import.meta.env.VITE_ENABLE_STRICTMODE);
const IsStrictMode = VITE_ENABLE_STRICTMODE ? StrictMode : React.Fragment;

createRoot(document.getElementById('root')!).render(
  <IsStrictMode>
    <App />
  </IsStrictMode>
);
