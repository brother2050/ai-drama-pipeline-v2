"""多平台分发

提供平台适配参数和视频规格校验。
实际上传功能需要对接各平台 API（目前返回适配参数）。
"""
from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

PLATFORM_PRESETS = {
    "douyin": {
        "resolution": [1080, 1920],
        "max_size_mb": 500,
        "max_duration_sec": 900,
        "aspect_ratio": "9:16",
        "codec": "h264",
        "formats": ["mp4"],
    },
    "bilibili": {
        "resolution": [1920, 1080],
        "max_size_mb": 2000,
        "max_duration_sec": 7200,
        "aspect_ratio": "16:9",
        "codec": "h264",
        "formats": ["mp4", "flv"],
    },
    "kuaishou": {
        "resolution": [1080, 1920],
        "max_size_mb": 500,
        "max_duration_sec": 600,
        "aspect_ratio": "9:16",
        "codec": "h264",
        "formats": ["mp4"],
    },
    "weixinshipin": {
        "resolution": [1080, 1920],
        "max_size_mb": 600,
        "max_duration_sec": 1800,
        "aspect_ratio": "9:16",
        "codec": "h264",
        "formats": ["mp4"],
    },
}


def get_video_info(video: str) -> dict:
    """获取视频基本信息"""
    try:
        import json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", video],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(r.stdout)
        fmt = info.get("format", {})
        stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        return {
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "duration": float(fmt.get("duration", 0)),
            "size_mb": round(int(fmt.get("size", 0)) / 1024 / 1024, 2),
            "codec": stream.get("codec_name", ""),
        }
    except Exception as e:
        logger.warning(f"获取视频信息失败: {e}")
        return {}


def check_platform_compat(video: str, platform: str) -> dict:
    """检查视频是否符合平台要求

    Returns:
        {"compatible": bool, "issues": list[str], "preset": dict}
    """
    preset = PLATFORM_PRESETS.get(platform)
    if not preset:
        return {"compatible": False, "issues": [f"未知平台: {platform}"], "preset": {}}

    info = get_video_info(video)
    if not info:
        return {"compatible": True, "issues": ["无法获取视频信息"], "preset": preset}

    issues = []

    # 分辨率检查
    pw, ph = preset["resolution"]
    vw, vh = info.get("width", 0), info.get("height", 0)
    if vw > 0 and vh > 0:
        expected_ratio = pw / ph  # 目标宽高比（标准 width/height）
        actual_ratio = vw / vh
        if abs(actual_ratio - expected_ratio) > 0.1:
            issues.append(f"宽高比不匹配: 视频 {vw}x{vh}，平台要求 {pw}x{ph}")

    # 大小检查
    max_mb = preset.get("max_size_mb", 9999)
    if info.get("size_mb", 0) > max_mb:
        issues.append(f"文件过大: {info['size_mb']}MB > {max_mb}MB")

    # 时长检查
    max_dur = preset.get("max_duration_sec", 9999)
    if info.get("duration", 0) > max_dur:
        issues.append(f"时长过长: {info['duration']:.0f}s > {max_dur}s")

    return {
        "compatible": len(issues) == 0,
        "issues": issues,
        "preset": preset,
        "video_info": info,
    }


def get_adapt_params(video: str, platform: str) -> dict:
    """获取平台适配参数（用于 ffmpeg 转码）

    Returns:
        {"ffmpeg_args": list[str], "preset": dict, "needs_transcode": bool}
    """
    preset = PLATFORM_PRESETS.get(platform, {})
    if not preset:
        return {"ffmpeg_args": [], "preset": {}, "needs_transcode": False}

    compat = check_platform_compat(video, platform)
    if compat["compatible"]:
        return {"ffmpeg_args": [], "preset": preset, "needs_transcode": False}

    # 构建 ffmpeg 转码参数
    pw, ph = preset["resolution"]
    args = [
        "-vf", f"scale={pw}:{ph}:force_original_aspect_ratio=decrease,pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
    ]
    return {"ffmpeg_args": args, "preset": preset, "needs_transcode": True}


def distribute(video: str, platforms: list[str] | None = None) -> dict[str, dict]:
    """分发到指定平台

    Args:
        video: 视频文件路径
        platforms: 目标平台列表，默认全部

    Returns:
        {platform: {"status": "ready", "preset": {...}, "compat": {...}}}
    """
    platforms = platforms or list(PLATFORM_PRESETS.keys())
    results = {}

    for p in platforms:
        preset = PLATFORM_PRESETS.get(p, {})
        if not preset:
            results[p] = {"status": "error", "reason": f"未知平台: {p}"}
            continue

        compat = check_platform_compat(video, p)
        adapt = get_adapt_params(video, p)

        results[p] = {
            "status": "ready" if compat["compatible"] else "needs_adapt",
            "preset": preset,
            "compatibility": compat,
            "adapt_params": adapt,
        }

        if compat["compatible"]:
            logger.info(f"✅ {p}: 视频符合要求")
        else:
            logger.info(f"⚠ {p}: 需要适配 — {', '.join(compat['issues'])}")

    return results
