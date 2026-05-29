"""转场效果 — ffmpeg concat + xfade 滤镜构建

改进: 多段视频 xfade offset 精确计算，音频/视频时间轴同步
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
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
        shutil.copy2(inputs[0], output)
        return output

    Path(output).parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    # 获取每个视频的精确时长
    durations = [_get_duration(p) for p in inputs]
    logger.debug(f"视频时长: {durations}")

    # 构建 ffmpeg 命令
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning"]

    # 输入
    for p in inputs:
        cmd.extend(["-i", p])

    # 构建 xfade 滤镜链
    filter_parts = []
    audio_parts = []
    xfade = TRANSITIONS.get(transition, "fade")

    if len(inputs) == 2:
        # 两段视频: 单次 xfade
        offset = max(0, durations[0] - duration)
        filter_parts.append(f"[0:v][1:v]xfade=transition={xfade}:duration={duration}:offset={offset}[v]")
    else:
        # 多段视频: 链式 xfade
        # offset_i = sum(durations[:i]) - duration * i
        # 用 round() 减少浮点累积误差
        prev_label = "0:v"

        for i in range(1, len(inputs)):
            offset = round(max(0, sum(durations[:i]) - duration * i), 3)

            out_label = f"v{i}" if i < len(inputs) - 1 else "v"
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition={xfade}:duration={duration}:offset={offset}[{out_label}]"
            )
            prev_label = out_label

    # 音频处理: 使用 acrossfade 或 amix 保持与视频同步
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
            # 多段音频: 使用 acrossfade（与 xfade 时间同步）
            if len(audio_inputs) == 2:
                audio_parts.append(
                    f"[{audio_inputs[0]}:a][{audio_inputs[1]}:a]acrossfade=d={duration}:c1=tri:c2=tri[a]"
                )
            else:
                # 多段: 链式 acrossfade
                prev_alabel = f"{audio_inputs[0]}:a"
                for i in range(1, len(audio_inputs)):
                    out_alabel = "a" if i == len(audio_inputs) - 1 else f"a{i}"
                    audio_parts.append(
                        f"[{prev_alabel}][{audio_inputs[i]}:a]acrossfade=d={duration}:c1=tri:c2=tri[{out_alabel}]"
                    )
                    prev_alabel = out_alabel

    # 合并 filter_complex
    all_filters = filter_parts + audio_parts
    if all_filters:
        cmd.extend(["-filter_complex", ";".join(all_filters)])
        cmd.extend(["-map", "[v]"])
        if audio_inputs:
            cmd.extend(["-map", "[a]"])

    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output])

    logger.debug(f"ffmpeg concat: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"转场拼接失败 (exit {r.returncode}): {r.stderr[-500:]}")

    return output
