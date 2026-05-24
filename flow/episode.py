"""集管理"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_episode_status(project_dir: str, episode: int) -> dict:
    """获取集状态"""
    out_dir = Path(project_dir) / "output" / f"e{episode:02d}"
    if not out_dir.exists():
        return {"episode": episode, "status": "not_started", "shots": 0}

    shot_dirs = sorted(out_dir.glob("s*"))
    shots_status = []
    for sd in shot_dirs:
        has_frame = (sd / "frame.png").exists()
        has_video = (sd / "video.mp4").exists()
        has_audio = (sd / "audio.wav").exists()
        has_final = (sd / "final.mp4").exists()
        shots_status.append({
            "shot_id": sd.name,
            "frame": has_frame, "video": has_video,
            "audio": has_audio, "final": has_final,
        })

    return {"episode": episode, "status": "in_progress", "shots": len(shots_status),
            "details": shots_status}
