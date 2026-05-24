"""转场效果 — ffmpeg concat + xfade 滤镜构建"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 转场类型 → ffmpeg xfade 过滤器
TRANSITIONS = {
    "crossfade": "fade",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "glitch": "fadeblack",
    "zoom_blur": "smoothleft",
    "circle_open": "circleopen",
    "circle_close": "circleclose",
}


def get_xfade_filter(transition: str, offset: float, duration: float) -> str:
    """生成 ffmpeg xfade 过滤器字符串"""
    xfade = TRANSITIONS.get(transition, "fade")
    return f"xfade=transition={xfade}:duration={duration}:offset={offset}"


def _get_duration(path: str) -> float:
    """获取视频时长（秒）"""
    from infra.ffmpeg import probe
    info = probe(path)
    return float(info.get("format", {}).get("duration", 0))


def build_concat_filter(inputs: list[str], output: str, transition: str = "crossfade",
                        duration: float = 0.5, timeout: int = 1200) -> str:
    """带转场的视频拼接

    Args:
        inputs: 输入视频路径列表
        output: 输出路径
        transition: 转场类型
        duration: 转场时长（秒）
        timeout: 超时时间

    Returns:
        输出文件路径
    """
    if not inputs:
        return ""
    if len(inputs) == 1:
        import shutil
        shutil.copy2(inputs[0], output)
        return output

    Path(output).parent.mkdir(parents=True, exist_ok=True)

    # 获取每个视频的时长
    durations = [_get_duration(p) for p in inputs]

    # 构建 ffmpeg 滤镜链
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning"]

    # 输入
    for p in inputs:
        cmd.extend(["-i", p])

    # 构建 xfade 滤镜链
    if len(inputs) == 2:
        offset = max(0, durations[0] - duration)
        xfade = TRANSITIONS.get(transition, "fade")
        filter_str = f"[0:v][1:v]xfade=transition={xfade}:duration={duration}:offset={offset}[v]"
        cmd.extend(["-filter_complex", filter_str, "-map", "[v]"])
    else:
        # 多段视频：链式 xfade
        filter_parts = []
        current_offset = 0.0
        prev_label = "0:v"

        for i in range(1, len(inputs)):
            current_offset = sum(durations[:i]) - duration * i
            current_offset = max(0, current_offset)
            xfade = TRANSITIONS.get(transition, "fade")
            out_label = f"v{i}" if i < len(inputs) - 1 else "v"
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition={xfade}:duration={duration}:offset={current_offset}[{out_label}]"
            )
            prev_label = out_label

        filter_str = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_str, "-map", "[v]"])

    # 音频处理（简单混合）
    audio_inputs = []
    for i, p in enumerate(inputs):
        from infra.ffmpeg import probe
        info = probe(p)
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        if has_audio:
            audio_inputs.append(i)

    if audio_inputs:
        if len(audio_inputs) == 1:
            cmd.extend(["-map", f"{audio_inputs[0]}:a"])
        else:
            # 多段音频用 amix
            audio_labels = "".join(f"[{i}:a]" for i in audio_inputs)
            audio_filter = f"{audio_labels}amix=inputs={len(audio_inputs)}:duration=longest[a]"
            if ";" in filter_str or filter_parts:
                # 追加到已有 filter_complex
                cmd_idx = cmd.index("-filter_complex")
                cmd[cmd_idx + 1] = cmd[cmd_idx + 1] + ";" + audio_filter
            else:
                cmd.extend(["-filter_complex", audio_filter])
            cmd.extend(["-map", "[a]"])

    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-y", output])

    logger.debug(f"ffmpeg concat: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"转场拼接失败 (exit {r.returncode}): {r.stderr[-500:]}")

    return output
