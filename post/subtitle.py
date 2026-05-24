"""字幕生成 — SRT 格式（考虑转场重叠）"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
        dialogue = shot.get("dialogue", "").strip()
        duration = float(shot.get("duration", 4))

        # current_time 已经是正确的起始时间（考虑了前面所有镜头的转场重叠）
        start = current_time

        # 非首段镜头: 实际时长减去转场重叠
        if i > 0 and transition_duration > 0:
            current_time += max(0, duration - transition_duration)
        else:
            current_time += duration

        if not dialogue or dialogue == "......":
            continue

        # 字幕结束时间 = 下一段画面开始时间（即当前段的可见结束时间）
        if i > 0 and transition_duration > 0:
            end = start + max(0, duration - transition_duration)
        else:
            end = start + duration
        start_str = _format_srt_time(start)
        end_str = _format_srt_time(end)
        lines.append(f"{idx}\n{start_str} --> {end_str}\n{dialogue}\n")
        idx += 1

    Path(output).write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"字幕生成: {output} ({idx-1} 条)")
    return output


def _format_srt_time(seconds: float) -> str:
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
