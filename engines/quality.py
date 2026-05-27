"""质量检查引擎 — 视频格式/面部一致性"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def check_video_format(path: str) -> dict:
    """检查视频格式"""
    if not Path(path).exists():
        return {"valid": False, "error": "文件不存在"}
    try:
        from infra.ffmpeg import probe
        info = probe(path)
        if not info:
            return {"valid": False, "error": "ffprobe 失败"}
        video_stream = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
        if not video_stream:
            return {"valid": False, "error": "无视频流"}
        return {
            "valid": True,
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "duration": float(info.get("format", {}).get("duration", 0)),
            "codec": video_stream.get("codec_name", ""),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}
