"""情绪分析引擎 — 从台词/动作提取情绪标签"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 中文情绪关键词
_KEYWORDS = {
    "angry": ["愤怒", "生气", "暴怒", "怒吼", "怒", "气愤"],
    "sad": ["悲伤", "哭泣", "流泪", "伤心", "难过", "哭"],
    "happy": ["开心", "高兴", "大笑", "欢笑", "笑", "快乐"],
    "worried": ["担心", "焦虑", "不安", "忧心", "担忧"],
    "surprised": ["惊讶", "震惊", "吃惊", "意外", "惊"],
    "smug": ["得意", "骄傲", "自满", "傲慢"],
    "serious": ["严肃", "认真", "庄重", "正经"],
    "calm": ["平静", "冷静", "淡定", "从容"],
    "determined": ["坚定", "决意", "果断", "下定决心"],
    "fearful": ["害怕", "恐惧", "畏惧", "胆怯"],
    "romantic": ["浪漫", "温柔", "深情", "爱意"],
    "action": ["奔跑", "追逐", "打斗", "跳跃", "冲刺"],
}


def analyze_emotion(text: str) -> str:
    """从文本分析情绪"""
    for emotion, keywords in _KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return emotion
    return "neutral"
