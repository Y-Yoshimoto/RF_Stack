
# -*- coding: utf-8 -*-


# HTTPクライアントのクラス定義

# ユニットテストコードサンプル
import httpx
# import asyncio
from abc import ABCMeta


# Clientの抽象クラス定義
class Client_ABC(metaclass=ABCMeta):
    """
    HTTPクライアント基底クラス
    このクラスは、指定されたベースURLに対してHTTPリクエストを送信するためのメソッドを提供
    Attributes:
        baseURL (str): ベースURL
        client (httpx.Client): 同期HTTPクライアント
        async_client (httpx.AsyncClient): 非同期HTTPクライアント
        headers (dict): 追加のリクエストヘッダー
    """
    # デフォルト基底ヘッダー
    defaultheaders = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    def __init__(self, domain: str, base_path: str, ssl: bool = False, headers: dict = None):
        """
        コンストラクタ
        HTTP接続の同期クライアントと非同期クライアントを初期化
        """
        # ベースURLを初期化
        self.base_url: str = f"https://{domain}{base_path}" if ssl else f"http://{domain}{base_path}"
        # 追加のヘッダーを設定
        self.headers = {**self.defaultheaders, **(headers or {})}

        # HTTPクライアントの初期化
        # https://www.python-httpx.org/advanced/clients/
        self.client = httpx.Client(base_url=self.base_url, timeout=None, follow_redirects=True, headers=self.headers)
        # 非同期HTTPクライアントの初期化
        # self.async_client = httpx.AsyncClient(base_url=self.base_url, timeout=None, follow_redirects=True, headers=self.headers)

    def close(self):
        """同期クライアントを明示的に閉じる"""
        if hasattr(self, 'client'):
            self.client.close()

    def __del__(self):
        """オブジェクトの削除時にを閉じる"""
        self.close()


    def _send_request(self, sendClient, method: str, path: str, params: dict = None, data: dict = None):
        """ メソッドに応じてHTTPリクエストを送信するヘルパーメソッド """
        if method.upper() == "GET":
            if data is None:
                return sendClient.get(path, params=params)
            else:
                # Body付きGETリクエストの処理
                return sendClient.send(httpx.Request("GET", path, json=data, params=params))
        elif method.upper() == "POST":
            return sendClient.post(path, json=data, params=params)
        elif method.upper() == "PUT":
            return sendClient.put(path, json=data, params=params)
        elif method.upper() == "DELETE":
            return sendClient.delete(path, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

    # 同期リクエスト
    def request(self, method: str, path: str, params: dict = None, data: dict = None):
        """
        指定されたパスに対してHTTPリクエストを送信
        Args:
            method (str): HTTPメソッド（GET, POST, PUT, DELETEなど）。
            path (str): リクエストのパス。
            params (dict): クエリパラメータ。
            data (dict): リクエストボディ。
        Returns:
            httpx.Response: レスポンスオブジェクト。
        """
        return self._send_request(self.client, method, path, params, data)

    # 非同期リクエスト(検証中)
    # async def async_request(self, method: str, path: str, params: dict = None, data: dict = None):
    #     """
    #     指定されたパスに対して非同期HTTPリクエストを送
    #     Args:
    #         method (str): HTTPメソッド（GET, POST, PUT, DELETEなど）。
    #         path (str): リクエストのパス。
    #         params (dict): クエリパラメータ。
    #         data (dict): リクエストボディ。
    #     Returns:
    #         httpx.Response: 非同期レスポンスオブジェクト。
    #     """
    #     return self._send_request(self.async_client, method, path, params, data)

# HttpClient.Client.py
class HttpClient(Client_ABC):
    """
    HTTPクライアントクラス。
    このクラスは、指定されたベースURLに対してHTTPリクエストを送信するためのメソッドを提供
    Attributes:
        domain (str): ドメイン名
        ssl (bool): SSLを使用するかどうか
        headers (dict): 追加のリクエストヘッダー
    """
    def __init__(self, domain: str, base_path: str, ssl: bool = False, headers: dict = None):
        super().__init__(domain=domain, base_path=base_path, ssl=ssl, headers=headers)
