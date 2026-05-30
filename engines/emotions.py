"""情绪分析引擎 — 从台词/动作提取情绪标签"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 情绪标签集
EMOTIONS = {"angry", "sad", "happy", "worried", "surprised", "smug",
            "serious", "calm", "determined", "fearful", "romantic",
            "action", "neutral"}

_EMOTION_SYSTEM = """你是情绪分析专家。根据输入的中文文本（台词或动作描述），判断最匹配的情绪标签。

可选标签：
- angry（愤怒）
- sad（悲伤）
- happy（开心）
- worried（担心）
- surprised（惊讶）
- smug（得意）
- serious（严肃）
- calm（平静）
- determined（坚定）
- fearful（害怕）
- romantic（浪漫/温柔）
- action（动作/激烈）
- neutral（中性/无明显情绪）

规则：
- 只输出标签英文名，不要任何额外文字
- 如果文本含"苦笑""假笑""嘲笑"等负面含义的笑，不要输出 happy
- 如果文本含"冷笑""怒笑"，输出 angry
- 优先考虑文本的整体语境，而非单个关键词"""


def analyze_emotion(text: str, llm=None) -> str:
    """从文本分析情绪（LLM 优先，关键词兜底）

    Args:
        text: 中文文本（台词或动作描述）
        llm: LLM 后端实例（可选）

    Returns:
        情绪标签字符串
    """
    if not text or not text.strip():
        return "neutral"

    text = text.strip()

    # 1. 优先用 LLM
    if llm:
        try:
            result = llm.chat(text, system=_EMOTION_SYSTEM, max_tokens=32)
            emotion = result.strip().lower().split()[0] if result else ""
            # 去掉可能的标点或多余字符
            emotion = re.sub(r'[^a-z]', '', emotion)
            if emotion in EMOTIONS:
                return emotion
            logger.debug(f"LLM 返回了未知情绪 '{result.strip()}'，回退到关键词匹配")
        except Exception as e:
            logger.debug(f"LLM 情绪分析失败，回退到关键词匹配: {e}")

    # 2. 兜底：关键词匹配（优先更长的关键词）
    return _keyword_match(text)


# ── 关键词兜底 ──

_KEYWORDS = {
    "angry": ["愤怒", "暴怒", "怒吼", "气愤", "怒骂", "冷笑", "怒笑"],
    "sad": ["悲伤", "哭泣", "流泪", "伤心", "难过", "苦笑", "哀伤"],
    "happy": ["开心", "高兴", "大笑", "欢笑", "快乐", "欣喜"],
    "worried": ["担心", "焦虑", "不安", "忧心", "担忧", "惶恐"],
    "surprised": ["惊讶", "震惊", "吃惊", "意外", "愕然"],
    "smug": ["得意", "骄傲", "自满", "傲慢"],
    "serious": ["严肃", "认真", "庄重", "正经"],
    "calm": ["平静", "冷静", "淡定", "从容"],
    "determined": ["坚定", "决意", "果断", "下定决心"],
    "fearful": ["害怕", "恐惧", "畏惧", "胆怯", "颤抖"],
    "romantic": ["浪漫", "温柔", "深情", "爱意", "含情"],
    "action": ["奔跑", "追逐", "打斗", "跳跃", "冲刺"],
}


def _keyword_match(text: str) -> str:
    """关键词匹配（优先更长的关键词，避免子串误判）"""
    best_match = "neutral"
    best_len = 0
    for emotion, keywords in _KEYWORDS.items():
        for kw in keywords:
            if kw in text and len(kw) > best_len:
                best_match = emotion
                best_len = len(kw)
    return best_match
