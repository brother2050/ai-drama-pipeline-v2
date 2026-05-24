"""分镜表读取器 — CSV 解析 + 数据验证"""
from __future__ import annotations
import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["load_storyboard", "validate_shot", "get_dominant_emotion"]

REQUIRED_FIELDS = ["episode", "shot_id", "scene", "characters", "action", "dialogue"]


def load_storyboard(path: str, episode: int | None = None) -> list[dict[str, Any]]:
    """加载分镜表 CSV"""
    if not Path(path).exists():
        logger.warning(f"分镜表不存在: {path}")
        return []

    shots = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if episode is not None and int(row.get("episode", 0)) != episode:
                continue
            shots.append(dict(row))

    shots.sort(key=lambda s: s.get("shot_id", "000"))
    logger.info(f"加载分镜: {len(shots)} 个镜头" + (f" (第{episode}集)" if episode else ""))
    return shots


def validate_shot(shot: dict) -> list[str]:
    """验证镜头数据完整性，返回错误列表"""
    if not shot:
        return ["镜头数据为空"]
    errors = []
    for field in REQUIRED_FIELDS:
        if not shot.get(field):
            errors.append(f"缺少必填字段: {field}")
    if shot.get("duration"):
        try:
            d = float(shot["duration"])
            if d <= 0:
                errors.append("duration 必须为正数")
        except ValueError:
            errors.append(f"duration 格式错误: {shot['duration']}")
    return errors


def get_dominant_emotion(shots: list[dict]) -> str:
    """获取镜头列表中的主要情绪"""
    from collections import Counter
    emotions = [s.get("emotion", "neutral") for s in shots if s.get("emotion")]
    if not emotions:
        return "neutral"
    return Counter(emotions).most_common(1)[0][0]
