// サービスワーカー
// fetchイベントをキャッチして、APIリクエストにトークンを追加するサンプル

// アクセストークンを保存する変数
let access_token = null;

//FetchEventを中継する
// 注意: 認証は BFF (HttpOnly の Cookie) で行うため、通常はトークンを設定しない (docs/architecture/02 §6.2)。
// トークンが未設定のときは中継せず、ブラウザの既定の処理に任せる。
// - init.headers を渡すと元のヘッダーが置き換わり、CSRF 対策の X-Requested-With: rf-stack が消えて 403 になるため、元のヘッダーを引き継ぐ。
// - トップレベル遷移 (/api/auth/app/login 等。mode: navigate) は RequestInit 付きで再構築できないため対象外とする。
self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (!access_token || request.mode === 'navigate') return;
    if (new URL(request.url).pathname.startsWith('/api/')) {
        const headers = new Headers(request.headers);
        headers.set('Authorization', access_token);
        event.respondWith(fetch(new Request(request, { headers })));
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