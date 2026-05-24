"""Redis 管理器"""
from __future__ import annotations
import logging
import os
import shutil
import socket
import subprocess

logger = logging.getLogger(__name__)


def is_redis_running(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def ensure_redis():
    """确保 Redis 运行"""
    if is_redis_running():
        return True

    logger.info("Redis 未运行，尝试启动...")
    redis = shutil.which("redis-server")
    if redis:
        subprocess.Popen([redis, "--daemonize", "yes"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time; time.sleep(1)
        if is_redis_running():
            logger.info("✅ Redis 已启动")
            return True

    # macOS Homebrew
    if shutil.which("brew"):
        subprocess.run(["brew", "services", "start", "redis"],
                      capture_output=True, timeout=30)
        import time; time.sleep(1)
        if is_redis_running():
            return True

    logger.warning("Redis 启动失败，请手动启动")
    return False
