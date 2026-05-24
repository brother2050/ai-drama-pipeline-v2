"""质量检查引擎 — 视频格式/面部一致性"""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def check_video_format(path: str) -> dict:
    """检查视频格式"""
    if not Path(path).exists():
        return {"valid": False, "error": "文件不存在"}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"valid": False, "error": "ffprobe 失败"}
        info = json.loads(r.stdout)
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


def check_audio_exists(path: str) -> bool:
    """检查视频是否包含音频流"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries", "stream=codec_type", path],
            capture_output=True, text=True, timeout=30)
        return "codec_type=audio" in r.stdout
    except Exception:
        return False
