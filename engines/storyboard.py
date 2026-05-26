"""分镜表读取器 — CSV 解析 + 数据验证 + 保存"""
from __future__ import annotations
import csv
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["load_storyboard", "validate_shot", "get_dominant_emotion", "save_storyboard"]

REQUIRED_FIELDS = ["episode", "shot_id", "scene", "characters", "action", "dialogue"]

STORYBOARD_FIELDNAMES = [
    "episode", "shot_id", "scene", "characters", "action", "dialogue",
    "camera", "shot_type", "duration", "outfit", "emotion",
    "action_en", "dialogue_en",
]


def load_storyboard(path: str, episode: int | None = None) -> list[dict[str, Any]]:
    """加载分镜表 CSV"""
    if not Path(path).exists():
        logger.warning(f"分镜表不存在: {path}")
        return []

    shots = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if episode is not None:
                try:
                    ep = int(row.get("episode", 0) or 0)
                except (ValueError, TypeError):
                    continue
                if ep != episode:
                    continue
            shots.append(dict(row))

    shots.sort(key=lambda s: s.get("shot_id", "000"))
    logger.info(f"加载分镜: {len(shots)} 个镜头" + (f" (第{episode}集)" if episode else ""))
    return shots


def save_storyboard(path: Path, shots: list[dict], episode: int, append: bool = False) -> None:
    """保存分镜到 CSV

    Args:
        path: CSV 文件路径
        shots: 要保存的镜头列表
        episode: 集数
        append: True 时保留其他集的镜头，False 时替换当前集
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if append and path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    ep = int(row.get("episode", 0) or 0)
                except (ValueError, TypeError):
                    ep = 0
                if ep != episode:
                    existing.append(row)

    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".csv.tmp")
    try:
        with os.fdopen(tmp_fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=STORYBOARD_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing + shots)
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
