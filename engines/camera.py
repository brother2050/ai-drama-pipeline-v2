"""机位/景别规范化"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CAMERA_ALIASES = {
    "环绕摇镜头": "环绕", "俯冲推镜": "缓慢推近",
    "横移跟拍": "跟随平移", "手持轻微晃动": "手持晃动",
}

VALID_CAMERAS = frozenset({
    "固定", "缓慢推近", "跟随平移", "手持晃动", "环绕", "俯视", "仰视",
})

VALID_SHOT_TYPES = frozenset({
    "特写", "近景", "中景", "过肩", "全身", "全景", "远景", "双人全景",
})

SHOT_KEYWORDS = ("特写", "近景", "中景", "过肩", "全身", "全景", "远景")


def normalize_camera(raw: str) -> str:
    if not raw:
        return "固定"
    raw = raw.strip().strip('"').strip("'")
    if not raw or raw == "无":
        return "固定"
    first = raw.split(",")[0].strip()
    result = CAMERA_ALIASES.get(first, first)
    # 校验返回值是否在合法集合中，不在则回退到默认
    if result not in VALID_CAMERAS:
        return "固定"
    return result


def normalize_shot_type(raw: str) -> str:
    if not raw:
        return "中景"
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return "中景"
    if raw in VALID_SHOT_TYPES:
        return raw
    for kw in SHOT_KEYWORDS:
        if kw in raw:
            return kw
    return "中景"
