"""网络工具 — 统一端口检测、连接测试"""
from __future__ import annotations

import socket

__all__ = ["port_ok"]


def port_ok(port: int, host: str = "127.0.0.1", timeout: float = 2) -> bool:
    """检测端口是否可达

    Args:
        port: 端口号
        host: 主机地址
        timeout: 连接超时（秒）

    Returns:
        True 如果端口可达
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
