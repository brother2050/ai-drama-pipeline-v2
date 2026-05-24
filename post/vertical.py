"""横转竖适配"""
from __future__ import annotations
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def to_vertical(video: str, output: str, mode: str = "face_track") -> str:
    """横转竖（9:16）"""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    # 获取原始尺寸
    import json
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video],
                       capture_output=True, text=True, timeout=30)
    info = json.loads(r.stdout)
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    w = int(stream.get("width", 1280))
    h = int(stream.get("height", 720))

    if h > w:
        shutil.copy2(video, output)
        return output

    target_w, target_h = 1080, 1920
    if mode == "center_crop":
        vf = f"crop={w}:{w*target_h//target_w},scale={target_w}:{target_h}"
    else:
        vf = (f"split[original][blur];[blur]scale={target_w}:{target_h},boxblur=20[bg];"
              f"[original]scale={target_w}:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

    cmd = [ffmpeg, "-y", "-i", video, "-vf", vf, "-c:a", "copy", output]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"横转竖失败: {r.stderr[-300:]}")
    return output
