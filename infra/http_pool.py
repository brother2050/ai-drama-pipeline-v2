"""共享 HTTP 连接池 — 全后端复用 httpx.Client

避免每个后端各自创建 httpx.Client 导致连接数膨胀。
按 base_url + timeout 组合缓存 Client 实例，进程退出时统一关闭。
"""
from __future__ import annotations

import logging
import threading

import httpx

logger = logging.getLogger(__name__)

__all__ = ["get_client", "get_fast_client", "shutdown_all"]

# 缓存: (base_url, timeout) → httpx.Client
_clients: dict[tuple[str, float], httpx.Client] = {}
_lock = threading.Lock()

# 常用超时档位
_DEFAULT_TIMEOUT = 60.0
_FAST_TIMEOUT = 5.0


def get_client(base_url: str = "", *, timeout: float = _DEFAULT_TIMEOUT) -> httpx.Client:
    """获取或创建共享 httpx.Client

    Args:
        base_url: 服务基础 URL（为空时返回无 base_url 的通用 Client）
        timeout: 请求超时（秒）

    Returns:
        共享的 httpx.Client 实例（连接池复用）
    """
    key = (base_url.rstrip("/") if base_url else "", timeout)
    client = _clients.get(key)
    if client is not None:
        return client
    with _lock:
        client = _clients.get(key)
        if client is not None:
            return client
        kwargs: dict = {
            "timeout": httpx.Timeout(timeout, connect=10),
            "follow_redirects": True,
            "limits": httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        }
        if base_url:
            kwargs["base_url"] = base_url.rstrip("/")
        client = httpx.Client(**kwargs)
        _clients[key] = client
        logger.debug(f"HTTP 连接池创建: base_url={base_url!r}, timeout={timeout}")
        return client


def get_fast_client(base_url: str = "") -> httpx.Client:
    """获取快速检查用 Client（5s 超时）"""
    return get_client(base_url, timeout=_FAST_TIMEOUT)


def shutdown_all() -> None:
    """关闭所有共享 Client（进程退出时调用）"""
    with _lock:
        for client in _clients.values():
            try:
                client.close()
            except Exception:
                pass
        _clients.clear()
        logger.debug("HTTP 连接池已全部关闭")
