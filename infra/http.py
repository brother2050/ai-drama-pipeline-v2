"""HTTP 客户端 — 统一远程 API 调用，基于 httpx

共享工具类，供后端模块使用。后端也可直接使用 httpx.Client。
提供连接池复用、健康检查、文件上传/下载等便捷方法。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

__all__ = ["ApiClient", "auth_headers"]


def auth_headers(api_key: str = "", content_type: str = "application/json") -> dict:
    """构建带 API Key 的请求头

    Args:
        api_key: API Key（为空时不添加 Authorization）
        content_type: Content-Type 值（为空时不添加）

    Returns:
        请求头字典
    """
    h = {}
    if content_type:
        h["Content-Type"] = content_type
    if api_key:
        # 同时发送两种认证头，兼容 CloudStudio 代理和 ComfyUI 原生认证
        h["X-API-Key"] = api_key
        h["Authorization"] = f"Bearer {api_key}"
    return h


class ApiClient:
    """远程 HTTP API 客户端

    特性:
    - 连接池复用（httpx.Client）
    - 统一超时/重试
    - 文件上传/下载
    - 健康检查
    """

    def __init__(self, base_url: str, *, timeout: float = 60, name: str = "api"):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.name = name
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10),
            follow_redirects=True,
        )

    def health_check(self) -> tuple[bool, str]:
        """健康检查"""
        for path in ("/health", "/", ""):
            try:
                r = self._client.get(path, timeout=5)
                return True, f"{self.name}: reachable (HTTP {r.status_code})"
            except Exception:
                continue
        return False, f"{self.name}: unreachable at {self.base_url}"

    def get_json(self, path: str, **kwargs) -> Any:
        r = self._client.get(path, **kwargs)
        r.raise_for_status()
        return r.json()

    def post_json(self, path: str, data: dict, **kwargs) -> Any:
        r = self._client.post(path, json=data, **kwargs)
        r.raise_for_status()
        return r.json()

    def post_multipart(self, path: str, files: dict[str, str],
                       data: dict[str, str] | None = None, **kwargs) -> bytes:
        """上传文件并返回响应内容"""
        upload_files = {}
        opened = []
        try:
            for field, filepath in files.items():
                fh = open(filepath, "rb")
                opened.append(fh)
                upload_files[field] = (Path(filepath).name, fh)
            r = self._client.post(path, files=upload_files, data=data, **kwargs)
            r.raise_for_status()
            return r.content
        finally:
            for fh in opened:
                fh.close()

    def download(self, url: str, output: str, **kwargs) -> str:
        """下载文件到本地"""
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with self._client.stream("GET", url, **kwargs) as r:
            r.raise_for_status()
            with open(output, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    f.write(chunk)
        return output

    def upload_and_download(self, path: str, upload_files: dict[str, str],
                            data: dict[str, str] | None = None, output: str = "",
                            **kwargs) -> bytes:
        """上传文件 → 下载结果"""
        return self.post_multipart(path, upload_files, data, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"ApiClient({self.base_url!r})"
