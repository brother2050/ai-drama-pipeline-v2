"""Redis 管理器"""
from __future__ import annotations
import logging
import shutil
import subprocess

from infra.network import port_ok

logger = logging.getLogger(__name__)


def is_redis_running(host: str = "127.0.0.1", port: int = 6379) -> bool:
    return port_ok(port, host)


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
