"""字幕生成 — SRT 格式，支持 Ollama 翻译"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_srt(shots: list[dict], output: str) -> str:
    """从分镜表生成 SRT 字幕"""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    lines = []
    idx = 1
    current_time = 0.0

    for shot in shots:
        dialogue = shot.get("dialogue", "").strip()
        if not dialogue or dialogue == "......":
            continue
        duration = float(shot.get("duration", 4))
        start = _format_srt_time(current_time)
        end = _format_srt_time(current_time + duration)
        lines.append(f"{idx}\n{start} --> {end}\n{dialogue}\n")
        idx += 1
        current_time += duration

    Path(output).write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"字幕生成: {output} ({idx-1} 条)")
    return output


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def translate_srt(srt_path: str, output: str, llm=None) -> str:
    """翻译字幕"""
    if not llm:
        logger.warning("无 LLM，跳过翻译")
        return srt_path
    content = Path(srt_path).read_text(encoding="utf-8")
    try:
        translated = llm.chat(f"Translate this SRT subtitle to English, keep format:\n{content}")
        Path(output).write_text(translated, encoding="utf-8")
        return output
    except Exception as e:
        logger.warning(f"翻译失败: {e}")
        return srt_path
