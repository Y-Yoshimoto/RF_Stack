/* eslint-disable */
/* @ts-nocheck */
// vite.config.ts

import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
// https://vite-pwa-org.netlify.app
import { VitePWA } from 'vite-plugin-pwa';
import type { ManifestOptions, VitePWAOptions } from 'vite-plugin-pwa';
// https://www.npmjs.com/package/rollup-plugin-visualizer
import { visualizer } from 'rollup-plugin-visualizer';

// Vite設定[https://vitejs.dev/config/]
export default defineConfig(({ mode }) => {
  // 環境変数取り出し
  const env = loadEnv(mode, process.cwd(), '');
  const APP_ENV = {
    VITE_APP_TITLE: env.VITE_APP_TITLE || "Vite App",
    VITE_APP_VERSION: env.VITE_APP_VERSION || "v_0.0.0",
    VITE_APP_ROUTER_BASE: env.VITE_APP_ROUTER_BASE || "/",
    VITE_ENABLE_PWA: JSON.parse(env.VITE_ENABLE_PWA) || false,
    VITE_ENABLE_STRICTMODE: JSON.parse(env.VITE_ENABLE_STRICTMODE) || false,
  };
  console.debug('APP_ENV:', APP_ENV);
  return {
    // ベースパスを指定
    base: APP_ENV.VITE_APP_ROUTER_BASE,
    // ソースコードのルートディレクトリとエイリアスの設定
    resolve: { alias: { '@': path.resolve(__dirname, './src') } },
    // プラグインの設定
    plugins: [
      react(),  //reactを使うためのプラグイン
      VitePWA({ //PWAを使うためのプラグイン(https://vite-pwa-org.netlify.app/guide/)
        registerType: 'autoUpdate',
        devOptions: { enabled: true },
        //サービスワーカの設定
        ...serviceworker,
        // manifest.jsonの設定
        manifest: manifest as ManifestOptions,
        disable: !APP_ENV.VITE_ENABLE_PWA,
      } as VitePWAOptions)],
    define: {
      __APP_ENV__: JSON.stringify(APP_ENV),
    },
    // ビルド設定
    build: {
      chunkSizeWarningLimit: 1024,
      minify: 'esbuild',
      rollupOptions: {
        plugins: [
          visualizer({
            filename: 'rollup-visualizer.html',
            gzipSize: true,
            // template: 'sunburst',
            // template: 'network',
          }),
        ],
      },
    },
    // サーバー起動設定
    server: {
      host: "0.0.0.0",
      port: 5173,
      // リバースプロキシの設定
      // proxy: reverseproxy(),
      proxy: reverseProxyCache(),
    }
  }
});

// マニフェスト設定
const manifest = {
  id: "React Template",
  name: "React Template",
  short_name: "Template",
  description: "React テンプレート",
  lang: "ja",
  icons: [
    {
      src: "favicon.ico",
      type: "image/x-icon",
      sizes: "256x256",
      purpose: "any"
    },
    {
      src: "icon.png",
      type: "image/png",
      sizes: "1024x1024",
      purpose: "any"

    }
  ],
  start_url: ".",
  display: "standalone",
  theme_color: "#005799",
  background_color: "#FEFEFE",
};


// リバースプロキシ設定
const reverseproxy = () => {
  // https://ja.vitejs.dev/config/server-options.html
  const API_HOST = `http://${process.env.VITE_API_HOST || 'fastapi_app:8000'}/`;
  return {
    '/': {
      target: API_HOST,
      changeOrigin: true,
      // rewrite: (path: string) => path.replace(/^\/api/, ''),
    },
  };
};

// RP
const reverseProxyCache = () => {
  const API_HOST = `http://${process.env.VITE_API_HOST || 'fastapi_app:8000'}/`;


  return {
    '/api': {
      target: API_HOST,
      changeOrigin: true,
      configure: (proxy: any) => {
        console.log('Proxy', proxy);
        // リクエスト時の処理
        proxy.on('proxyReq', proxyReq);
        proxy.on('proxyRes', proxyRes);
        //selfHandleResponse: true, // ← 自分でレスポンス処理を制御する
        // onProxyRes: async (proxyRes, req, res) => {
        //   const key = `${req.method}:${req.url}`
        //   console.log('onProxyRes key:', key)
        // },
        // onProxyReq: async (proxyReq: any, req: any, res: any) => {
        //   const key = `${req.method}:${req.url}`
        //   console.log('onProxyReq key:', key)
        //   proxyReq.path = req.url.replace(/^\/api/, '')
        //   proxyReq.end();
        // },
        // configure: (proxy) => {
        //   console.log('Proxy', proxy);
        //   proxy.on('proxyReq', async (proxyReq, req, res, options) => {
        //     const key = `${req.method}:${req.url}`
        //     const now = Date.now()

        //     // キャッシュヒット確認
        //     const cached = cache.get(key)
        //     if (cached && (now - cached.time) < TTL) {
        //       console.log(`[CACHE HIT] ${req.url}`)
        //       res.writeHead(200, { 'Content-Type': 'application/json' })
        //       res.end(JSON.stringify(cached.data))
        //       proxyReq.destroy() // 本来のリクエストはキャンセル
        //       return
        //     }

        //     // 通常通りバックエンドへfetchしてレスポンスをキャッシュ
        //     proxyReq.on('abort', () => {
        //       // クライアントがキャンセルした場合に備えてabortイベントを監視
        //     })
        //   })

        //   proxy.on('proxyRes', async (proxyRes, req, res) => {
        //     const key = `${req.method}:${req.url}`

        //     // レスポンスをバッファに読み込み
        //     const bodyChunks = []
        //     proxyRes.on('data', chunk => bodyChunks.push(chunk))
        //     proxyRes.on('end', () => {
        //       const body = Buffer.concat(bodyChunks).toString()

        //       try {
        //         const json = JSON.parse(body)
        //         console.log(`[CACHE SET] ${req.url}`)
        //         cache.set(key, { time: Date.now(), data: json })
        //       } catch {
        //         // JSONでない場合はキャッシュしない
        //       }

        //       // クライアントにレスポンスを返す
        //       res.writeHead(proxyRes.statusCode, proxyRes.headers)
        //       res.end(body)
        //     })
        //   })
        // },
      },
    }
  };
};

// リバースプロキシ設定
// 簡易キャッシュ/Strictモードの2回目のレスポンスを返す
const cache = new Map()
const TTL = 300 // 300ms
//// リクエスト加工
const proxyReq = async (proxyReq: any, req: any, res: any) => {
  const key = `${req.method}:${req.url}`
  // console.debug('onProxyReq key:', key)
  // proxyReq.path = req.url.replace(/^\/api/, '')
  // キャッシュヒット確認
  const cached = cache.get(key)
  // TTL内であればキャッシュを返す
  if (cached && (Date.now() - cached.time) < TTL) {
    // console.log(`[CACHE HIT] Key: ${key}`)
    // キャッシュが"203 Non-Authoritative Information"レスポンスとして返す
    res.writeHead(203, cached.headers);
    res.end(cached.data);
    // res.end(JSON.stringify(cached.data))
    // 元のリクエストを中止
    proxyReq.abort();
  }
  return
};

//// レスポンス加工
const proxyRes = async (proxyRes: any, req: any, res: any) => {
  const key = `${req.method}:${req.url}`
  // console.debug(`proxyRes Key: ${key}`)
  // レスポンスをバッファに読み込み
  let bodyChunks: any[] = []
  proxyRes.on('data', (chunk: any) => bodyChunks.push(chunk))
  proxyRes.on('end', () => {
    const body = Buffer.concat(bodyChunks).toString()
    // レスポンスをキャッシュに保存する
    try {
      // cache.set(key, { time: Date.now(), data: JSON.parse(body), headers: proxyRes.headers })
      cache.set(key, { time: Date.now(), data: body, headers: proxyRes.headers })
      // console.log(`[CACHE ADD] Key: ${key}`)
    } catch {
      console.error(`Add Cache Error. Key: ${key}`);
    }
    // Cacheの中に期限切れのデータがあればクリーンアップ
    clearCache();
    // クライアントにレスポンスを返す
    res.end(body)
  })
};

// TTLを超過したキャッシュを削除する関数
const clearCache = async () => {
  cache.forEach((v, k) => { if ((Date.now() - v.time) > TTL) cache.delete(k); });
};


// サービスワーカ設定
// https://vite-pwa-org.netlify.app/guide/inject-manifest.html
const serviceworker = {
  strategies: 'injectManifest',
  injectManifest: {
    injectionPoint: undefined
  },
  srcDir: 'src',
  filename: 'serviceworker.js',
}

