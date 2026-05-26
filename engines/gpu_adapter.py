"""GPU 适配器 — 从用户配置读取生成参数

项目本身不使用 GPU，GPU 由三方工具（ComfyUI 等）管理。
不再本地检测 nvidia-smi，参数从 config/system.yaml → generation 段读取，
未配置时使用合理默认值并给出配置建议。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_gpu_config(vram_mb: int | None = None, config: dict | None = None) -> dict:
    """返回生成参数配置（从用户配置读取，不检测本地 GPU）

    Args:
        vram_mb: 已废弃，保留兼容性，忽略。
        config: 完整配置字典（Config.data），传入时优先读取 generation 段。

    Returns:
        包含 resolution / image_steps / video_frames / image_backend / video_backend 的字典。
    """
    from infra.gpu import get_generation_config
    return get_generation_config(config)
