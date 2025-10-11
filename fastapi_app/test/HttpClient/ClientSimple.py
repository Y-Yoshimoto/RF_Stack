
# -*- coding: utf-8 -*-


# HTTPクライアントのクラス定義

# ユニットテストコードサンプル
import httpx

from abc import ABCMeta

# Clientの抽象クラス定義
class Client_ABC(metaclass=ABCMeta):
    """
    HTTPクライアントの抽象クラス。
    このクラスは、HTTPリクエストを送信するためのメソッドを定義します。
    """
    def generateURL(self, path: str):
        pass
    def get(self, path: str):
        pass 
    def post(self, path: str, data: dict):
        pass
    def put(self, path: str, data: dict):
        pass
    def delete(self, path: str):
        pass


# HttpClient.Client.py
class Client(Client_ABC):
    """
    HTTPクライアントクラス。
    このクラスは、指定されたベースURLに対してHTTPリクエストを送信するためのメソッドを提供します。
    Attributes:
        baseURL (str): リクエストのベースURL。
    """
    def __init__(self, baseURL: str):
        self.baseURL: str = baseURL
    
    def generateURL(self, path: str):
        """指定されたパスを基に完全なURLを生成する"""
        # return f"{self.baseURL}/{path}" if path else self.baseURL
        return f"{self.baseURL}/{path}"

    # GETリクエスト
    def get(self, path: str):
        """
        指定されたパスに対してGETリクエストを送信する。
        Args:
            path (str): リクエストのパス。
        Returns:
            httpx.Response: レスポンスオブジェクト。
        """
        url = self.generateURL(path)
        with httpx.Client() as client:
            return client.get(url)
        
    # POSTリクエスト
    def post(self, path: str, data: dict):
        """
        指定されたパスに対してPOSTリクエストを送信する。
        Args:
            path (str): リクエストのパス。
            data (dict): 送信するデータ。
        Returns:
            httpx.Response: レスポンスオブジェクト。
        """
        url = self.generateURL(path)
        with httpx.Client() as client:
            return client.post(url, json=data)
        
    # PUTリクエスト
    def put(self, path: str, data: dict):
        """
        指定されたパスに対してPUTリクエストを送信する。
        Args:
            path (str): リクエストのパス。
            data (dict): 送信するデータ。
        Returns:
            httpx.Response: レスポンスオブジェクト。
        """
        url = self.generateURL(path)
        with httpx.Client() as client:
            return client.put(url, json=data)
    
    # DELETEリクエスト
    def delete(self, path: str):
        """
        指定されたパスに対してDELETEリクエストを送信する。
        Args:
            path (str): リクエストのパス。
        Returns:
            httpx.Response: レスポンスオブジェクト。
        """
        url = self.generateURL(path)
        with httpx.Client() as client:
            return client.delete(url)