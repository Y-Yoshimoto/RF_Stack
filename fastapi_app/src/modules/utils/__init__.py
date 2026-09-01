#!/usr/bin/env python
# coding:utf-8
# 汎用ユーティリティモジュール

# UUID生成
import uuid


def generate_uuid() -> str:
    """
        UUIDを生成して文字列で返す
        return: UUID文字列
    """
    return str(uuid.uuid4())
