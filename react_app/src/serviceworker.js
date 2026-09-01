// サービスワーカー
// fetchイベントをキャッチして、APIリクエストにトークンを追加するサンプル

// アクセストークンを保存する変数
let access_token = null;

//FetchEventを中継する
self.addEventListener("fetch", (event) => {
    if (event.request.url.includes('/api')) {
        // console.debug("SW fetch API", event.request.url);
        //console.dir(event.request.headers);
        event.respondWith(fetch(event.request, { headers: { 'Authorization': access_token } }));
    }
});

// トークン受け取り処理
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'SET_TOKEN') {
        access_token = event.data.token;
        // トークンを保存する処理
        console.log('Token set:', access_token);
    }
});

/* // トークン追加アプリケーション側の実装例
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(registration => {
        const access_token = 'myToken'; // 設定するトークン
        registration.active.postMessage({ type: 'SET_TOKEN', access_token });
    });
}*/