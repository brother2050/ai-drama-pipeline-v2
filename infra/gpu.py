"""GPU / 生成参数配置 — 从用户配置热读取

项目本身不使用 GPU，GPU 由三方工具（ComfyUI 等）管理。
本模块提供生成参数（分辨率、步数等）的配置读取。
Config 对象支持 mtime 热读取，文件改了即时生效。
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
}


def get_generation_config(config=None) -> dict:
    """从配置读取生成参数（支持热读取）。

    Args:
        config: Config 对象 或 dict。传 Config 对象时自动检测文件变化并重载；
                传 dict 时直接读取；不传则自行实例化 Config。

    Returns:
        包含 resolution / image_steps / video_frames 等键的字典。
    """
    result = dict(_DEFAULTS)

    # 获取配置数据
    if config is None:
        # 自行加载 Config（支持热读取）
        try:
            from infra.config import Config
            config = Config()
        except Exception as e:
            logger.debug(f"无法加载 Config: {e}")
            result["note"] = "无法加载配置文件，使用默认值"
            return result

    # Config 对象：通过 .data 属性触发 mtime 检测 + 自动重载
    if hasattr(config, "data"):
        gen = config.get("generation", {})
    else:
        # dict 快照（向后兼容）
        gen = config.get("generation", {}) if isinstance(config, dict) else {}

    if gen:
        for key in ("resolution", "image_steps", "video_frames",
                     "image_backend", "video_backend"):
            if key in gen and gen[key] is not None:
                result[key] = gen[key]
    else:
        result["note"] = "未配置 generation 段，使用默认值。建议在 config/system.yaml 中添加：\n" \
                         "generation:\n" \
                         "  resolution: [512, 512]   # [宽, 高]\n" \
                         "  image_steps: 20          # 生图步数\n" \
                         "  video_frames: 8          # 视频帧数"

    return result
