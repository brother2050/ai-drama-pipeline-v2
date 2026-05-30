"""字幕生成 — SRT 格式（考虑转场重叠）"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_dialogue(text: str) -> str:
    """清理台词中的特殊字符，防止破坏 SRT 格式"""
    # 换行符替换为空格（SRT 用空行分隔条目，换行会破坏格式）
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # 合并连续空格
    import re
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_srt(shots: list[dict], output: str, *,
                 transition_duration: float = 0.0) -> str:
    """从分镜表生成 SRT 字幕

    Args:
        shots: 镜头列表
        output: 输出 SRT 路径
        transition_duration: 转场时长（秒），用于修正时间轴偏移
    """
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    lines = []
    idx = 1
    current_time = 0.0

    for i, shot in enumerate(shots):
        dialogue = _sanitize_dialogue(shot.get("dialogue", ""))
        try:
            duration = float(shot.get("duration", 4))
        except (ValueError, TypeError):
            duration = 4.0

        # current_time 已经是正确的起始时间（考虑了前面所有镜头的转场重叠）
        start = current_time

        # 非首段镜头: 实际时长减去转场重叠
        if i > 0 and transition_duration > 0:
            current_time += max(0, duration - transition_duration)
        else:
            current_time += duration

        if not dialogue or dialogue == "......":
            continue

        # 字幕结束时间 = 下一段画面开始时间
        end = current_time
        start_str = _format_srt_time(start)
        end_str = _format_srt_time(end)
        lines.append(f"{idx}\n{start_str} --> {end_str}\n{dialogue}\n")
        idx += 1

    fd, tmp = tempfile.mkstemp(dir=str(Path(output).parent), suffix=".srt.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.replace(tmp, output)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info(f"字幕生成: {output} ({idx-1} 条)")
    return output


def _format_srt_time(seconds: float) -> str:
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
