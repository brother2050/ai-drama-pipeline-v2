"""转场效果"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# 转场类型→ffmpeg xfade 过滤器
TRANSITIONS = {
    "crossfade": "fade",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "glitch": "fadeblack",
    "zoom_blur": "smoothleft",
    "circle_open": "circleopen",
    "circle_close": "circleclose",
}


def get_xfade_filter(transition: str, offset: float, duration: float) -> str:
    """生成 ffmpeg xfade 过滤器字符串"""
    xfade = TRANSITIONS.get(transition, "fade")
    return f"xfade=transition={xfade}:duration={duration}:offset={offset}"
