"""横转竖适配

支持两种模式：
- center_crop: 居中裁剪，简单高效
- face_track: 背景模糊 + 人物居中（当前为 blur_bg 实现，
  如需真正人脸追踪请安装 face_recognition/insightface）
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _find_face_center(video: str) -> tuple[int, int] | None:
    """尝试检测视频中的人脸中心位置

    Returns:
        (x, y) 人脸中心坐标，或 None
    """
    try:
        import face_recognition
        import cv2
        cap = cv2.VideoCapture(video)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        rgb = frame[:, :, ::-1]
        locations = face_recognition.face_locations(rgb)
        if not locations:
            return None
        # 取第一个人脸的中心
        top, right, bottom, left = locations[0]
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        return (cx, cy)
    except ImportError:
        return None
    except Exception:
        return None


def to_vertical(video: str, output: str, mode: str = "face_track") -> str:
    """横转竖（9:16）

    Args:
        video: 输入视频路径
        output: 输出视频路径
        mode: "center_crop" 或 "face_track"

    Returns:
        输出文件路径
    """
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

    # 已经是竖屏
    if h > w:
        shutil.copy2(video, output)
        return output

    target_w, target_h = 1080, 1920

    if mode == "center_crop":
        vf = f"crop={w}:{w*target_h//target_w},scale={target_w}:{target_h}"
    else:
        # face_track 模式：尝试检测人脸中心，回退到 blur_bg
        face_pos = _find_face_center(video)
        if face_pos:
            cx, cy = face_pos
            logger.info(f"检测到人脸中心: ({cx}, {cy})")
            # 计算裁剪区域，以人脸为中心
            crop_w = int(w * target_h / target_w)  # 保持目标宽高比的裁剪宽度
            crop_x = max(0, min(cx - crop_w // 2, w - crop_w))
            vf = (f"crop={crop_w}:{h}:{crop_x}:0,scale={target_w}:{target_h}")
        else:
            logger.info("未检测到人脸，使用模糊背景模式")
            vf = (f"split[original][blur];[blur]scale={target_w}:{target_h},boxblur=20[bg];"
                  f"[original]scale={target_w}:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

    cmd = [ffmpeg, "-y", "-i", video, "-vf", vf, "-c:a", "copy", output]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"横转竖失败: {r.stderr[-300:]}")
    return output
