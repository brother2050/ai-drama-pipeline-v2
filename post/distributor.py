"""多平台分发"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PLATFORM_PRESETS = {
    "douyin": {"resolution": [1080, 1920], "max_size_mb": 500},
    "bilibili": {"resolution": [1920, 1080], "max_size_mb": 2000},
    "kuaishou": {"resolution": [1080, 1920], "max_size_mb": 500},
    "weixinshipin": {"resolution": [1080, 1920], "max_size_mb": 600},
}


def distribute(video: str, platforms: list[str] | None = None) -> dict[str, str]:
    """分发到指定平台（目前仅返回平台配置信息）"""
    platforms = platforms or list(PLATFORM_PRESETS.keys())
    results = {}
    for p in platforms:
        preset = PLATFORM_PRESETS.get(p, {})
        logger.info(f"分发到 {p}: {preset}")
        results[p] = {"status": "ready", "preset": preset}
    return results
