"""Prompt 工程引擎 — 中文→英文翻译 + ComfyUI Prompt 构建"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 情绪→英文标签映射
EMOTION_MAP = {
    "angry": "angry, furrowed brows, clenched jaw",
    "sad": "sad, teary eyes, downturned mouth",
    "happy": "happy, bright smile, sparkling eyes",
    "worried": "worried, anxious expression, biting lip",
    "surprised": "surprised, wide eyes, open mouth",
    "smug": "smug, slight smirk, raised chin",
    "serious": "serious, focused expression, firm gaze",
    "calm": "calm, serene expression, relaxed posture",
    "determined": "determined, intense gaze, set jaw",
    "fearful": "fearful, trembling, wide eyes",
    "neutral": "neutral expression, natural pose",
    "romantic": "romantic, soft gaze, gentle smile",
    "action": "action pose, intense expression, dynamic",
}

# 景别→英文描述
SHOT_TYPE_MAP = {
    "特写": "extreme close-up shot, detailed face",
    "近景": "close-up shot, head and shoulders",
    "中景": "medium shot, waist up",
    "过肩": "over-the-shoulder shot",
    "全身": "full body shot",
    "全景": "wide shot, full scene",
    "远景": "extreme wide shot, establishing shot",
    "双人全景": "two-shot, both characters visible",
}

# 运镜→英文描述
CAMERA_MAP = {
    "固定": "static camera",
    "缓慢推近": "slow zoom in, dolly in",
    "跟随平移": "tracking shot, pan",
    "手持晃动": "handheld camera, slight shake",
    "环绕": "orbiting camera, 360 degree",
    "俯视": "top-down shot, bird's eye view",
    "仰视": "low angle shot, looking up",
}


def build_prompt(shot: dict, character_desc: str = "", scene_desc: str = "",
                 style: str = "cinematic", genre: str = "urban") -> str:
    """从镜头数据构建 ComfyUI Prompt"""
    parts = []

    # 风格前缀
    if style:
        parts.append(f"{style} style")
    if genre:
        parts.append(f"{genre} atmosphere")

    # 场景
    if scene_desc:
        parts.append(scene_desc)

    # 角色
    if character_desc:
        parts.append(character_desc)

    # 动作
    action = shot.get("action_en") or shot.get("action", "")
    if action:
        parts.append(action)

    # 情绪
    emotion = shot.get("emotion", "neutral")
    emotion_desc = EMOTION_MAP.get(emotion, EMOTION_MAP.get("neutral", "neutral expression"))
    parts.append(emotion_desc)

    # 景别
    shot_type = shot.get("shot_type", "中景")
    parts.append(SHOT_TYPE_MAP.get(shot_type, "medium shot"))

    # 运镜
    camera = shot.get("camera", "固定")
    parts.append(CAMERA_MAP.get(camera, "static camera"))

    return ", ".join(parts)


def translate_to_english(text: str, llm=None) -> str:
    """中文→英文翻译（使用 LLM 或回退）"""
    if not text:
        return ""
    # 简单回退：如果已经是英文直接返回
    if all(ord(c) < 128 for c in text):
        return text
    if llm:
        try:
            return llm.chat(f"Translate to English, output only the translation: {text}",
                          system="You are a professional translator.")
        except Exception as e:
            logger.warning(f"LLM translation failed: {e}")
    # 回退：返回原文
    return text
