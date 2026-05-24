"""视频一致性检查"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def check_video_consistency(video_path: str, ref_images: list[str]) -> dict:
    """检查视频中角色是否与参考图一致"""
    # placeholder — 实际需要 face recognition
    return {"consistent": True, "score": 0.8, "video": video_path}
