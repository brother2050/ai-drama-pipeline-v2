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
        has_synced = (sd / "synced.mp4").exists()
        shots_status.append({
            "shot_id": sd.name,
            "frame": has_frame, "video": has_video,
            "audio": has_audio, "synced": has_synced,
        })

    # 检查最终产物
    has_final = any(out_dir.glob("*_final.mp4"))
    has_concat = any(out_dir.glob("*_concat.mp4"))

    return {"episode": episode,
            "status": "done" if has_final else ("in_progress" if has_concat or shot_dirs else "not_started"),
            "shots": len(shots_status),
            "final_video": str(next(out_dir.glob("*_final.mp4"), "")),
            "details": shots_status}
