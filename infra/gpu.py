"""GPU / 生成参数配置 — 从用户配置读取

项目本身不使用 GPU，GPU 由三方工具（ComfyUI 等）管理。
本模块提供生成参数（分辨率、步数等）的配置读取，用户可在 system.yaml 的
`generation` 段自定义，未配置时使用合理默认值。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 默认生成参数（用户未配置时使用）
_DEFAULTS: dict[str, Any] = {
    "resolution": [512, 512],
    "image_steps": 20,
    "video_frames": 8,
    "image_backend": "sd15",
    "video_backend": "animatediff",
    "note": "默认值，可在 config/system.yaml → generation 段自定义",
}


def detect_gpu() -> dict:
    """兼容旧接口 — 返回占位信息（不检测本地 GPU）"""
    return {"name": "N/A", "vram_mb": 0, "cuda": "N/A", "available": False}


def get_generation_config(config: dict | None = None) -> dict:
    """从配置读取生成参数，未配置的字段使用默认值提示。

    Args:
        config: 完整配置字典（Config.data），传入时优先读取其中的 generation 段。

    Returns:
        包含 resolution / image_steps / video_frames 等键的字典。
    """
    result = dict(_DEFAULTS)

    # 从配置读取 generation 段
    gen = {}
    if config:
        gen = config.get("generation", {})

    if gen:
        for key in ("resolution", "image_steps", "video_frames",
                     "image_backend", "video_backend"):
            if key in gen and gen[key] is not None:
                result[key] = gen[key]
        result["note"] = "来自 config/system.yaml → generation"
    else:
        result["note"] = "未配置 generation 段，使用默认值。建议在 config/system.yaml 中添加：\n" \
                         "generation:\n" \
                         "  resolution: [512, 512]   # [宽, 高]\n" \
                         "  image_steps: 20          # 生图步数\n" \
                         "  video_frames: 8          # 视频帧数\n" \
                         "  # image_backend: sd15\n" \
                         "  # video_backend: animatediff"

    return result
