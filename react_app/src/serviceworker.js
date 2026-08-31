// サービスワーカー
// fetchイベントをキャッチして、APIリクエストにトークンを追加するサンプル

// アクセストークンを保存する変数
let accessToken = null;

//FetchEventを中継する
self.addEventListener("fetch", (event) => {
    if (event.request.url.includes('/api')) {
        event.respondWith(fetch(event.request));
    }
});

// トークン受け取り処理
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'SET_TOKEN') {
        accessToken = event.data.token;
        // トークンを保存する処理
        console.log('Token set:', accessToken);
    }
});

/* // トークン追加アプリケーション側の実装例
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(registration => {
        const accessToken = 'myToken'; // 設定するトークン
        registration.active.postMessage({ type: 'SET_TOKEN', accessToken });
    });
}*/