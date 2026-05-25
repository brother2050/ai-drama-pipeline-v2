"""GPU 适配器 — 使用默认配置

项目本身不使用 GPU，GPU 由三方工具（ComfyUI 等）管理。
本地检测 nvidia-smi 无意义，直接使用 API 模式默认配置。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 默认配置（API 模式 / 无本地 GPU）
_DEFAULT_CONFIG = {
    "image_backend": "sd15",
    "video_backend": "animatediff",
    "resolution": [512, 512],
    "image_steps": 20,
    "video_frames": 8,
    "vram_mb": 0,
    "note": "本地不检测 GPU，由三方工具管理",
}


def get_gpu_config(vram_mb: int | None = None) -> dict:
    """返回默认配置（不检测本地 GPU）"""
    return dict(_DEFAULT_CONFIG)
