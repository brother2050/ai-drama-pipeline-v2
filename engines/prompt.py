"""Prompt 工程引擎 — 中文→英文翻译 + ComfyUI Prompt 构建"""
from __future__ import annotations
import logging
import re
import urllib.parse
import urllib.request

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


def _strip_dialogue(text: str) -> str:
    """清理 action 中的对话/台词内容，防止模型将文字渲染进画面

    处理:
    - 中文引号: "xxx" / 'xxx' / 「xxx」/ 『xxx』
    - 英文引号: "xxx" / 'xxx'
    - "说：xxx" / "喊：xxx" / "道：xxx" 等模式
    - 完整的对话行

    注意：必须先处理 says:/说：模式，再删引号内容，否则引号被删后模式匹配失效
    """
    if not text:
        return text

    # 1. 先处理 "说/喊/道/问/答/嘟囔/嘀咕：后面的内容"（中文模式，只删引号内对话，保留后续动作）
    #    注意：多字词（嘟囔、嘀咕）必须用 | 分支，不能放在 [...] 字符类中
    text = re.sub(r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])\s*[：:]\s*[""「].*?[""」]', '', text)
    # 兜底：说：后面无引号的短对话（最多30字符到逗号/句号）
    text = re.sub(r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])\s*[：:]\s*[^，。,.]{0,30}[，。,.]?\s*', '', text)
    # 2. 先处理英文 says: 后的引号对话内容（保留后续动作）
    _SPEECH = r'(?:says?|said|asks?|answers?|replies?|shouts?|yells?|whispers?|mutters?|screams?|cries?|exclaims?|mutters?|responds?|states?|remarks?|calls?|begs?|pleads?|demands?|insists?|suggests?)'
    text = re.sub(rf'\b{_SPEECH}\s*:\s*"[^"]*"', '', text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{_SPEECH}\s*:\s*'[^']*'", '', text, flags=re.IGNORECASE)
    # 3. 移除 says: 后面无引号的短内容（对话）
    text = re.sub(rf'\b{_SPEECH}\s*:\s*[^,.]{{0,30}}[,.]?\s*', ' ', text, flags=re.IGNORECASE)
    # 4. 最后才移除残留的引号内容（中文引号）
    text = re.sub(r'[""「『].*?[""」』]', '', text)
    # 5. 移除残留的英文引号内容
    text = re.sub(r'"[^"]*"', '', text)
    text = re.sub(r"'[^']*'", '', text)
    # 清理多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def build_prompt(shot: dict, character_desc: str = "", scene_desc: str = "",
                 style: str = "cinematic", genre: str = "urban",
                 llm=None) -> str:
    """从镜头数据构建 ComfyUI Prompt"""
    parts = []

    # 风格前缀
    if style:
        parts.append(f"{style} style")
    if genre:
        parts.append(f"{genre} atmosphere")

    # 场景
    if scene_desc:
        if any(ord(c) > 127 for c in scene_desc):
            scene_desc = translate_to_english(scene_desc, llm=llm)
        parts.append(scene_desc)

    # 角色
    if character_desc:
        # 中文描述需要翻译为英文才能被 CLIP 正确编码
        if any(ord(c) > 127 for c in character_desc):
            character_desc = translate_to_english(character_desc, llm=llm)
        parts.append(character_desc)

    # 动作（清理对话内容，防止模型将台词渲染成画面文字）
    action = shot.get("action_en")
    if not action:
        action = shot.get("action", "")
        if action:
            action = _strip_dialogue(action)
            action = translate_to_english(action, llm=llm)
    else:
        action = _strip_dialogue(action)
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


# 常见中文外貌描述→英文映射（兜底用，覆盖常见词）
_TRANSLATE_API = "http://shanhe.kim/api/fany/fanyi.php"
_translate_cache: dict[str, str] = {}
_CACHE_MAX_SIZE = 4096


def _cache_set(key: str, value: str) -> None:
    if len(_translate_cache) >= _CACHE_MAX_SIZE:
        # 淘汰最早插入的一批条目（FIFO 近似），避免 clear() 导致缓存雪崩
        evict_count = _CACHE_MAX_SIZE // 4
        for old_key in list(_translate_cache)[:evict_count]:
            del _translate_cache[old_key]
    _translate_cache[key] = value


def _http_translate(text: str) -> str:
    """通过山河翻译 API 进行中→英翻译（带缓存）"""
    if text in _translate_cache:
        return _translate_cache[text]
    try:
        url = f"{_TRANSLATE_API}?msg={urllib.parse.quote(text)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ai-drama-pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # 返回格式: "内容：xxx<br>结果：yyy" 或 "内容：xxx\n结果：yyy"
        m = re.search(r"结果[：:]\s*(.+)", raw, re.DOTALL)
        if m:
            result = m.group(1).strip()
            # 去掉可能残留的 HTML 标签
            result = re.sub(r"<[^>]+>", "", result).strip()
            if result:
                _cache_set(text, result)
                logger.debug(f"HTTP 翻译成功: {text[:30]} → {result[:30]}")
                return result
        logger.warning(f"HTTP 翻译返回格式异常: {raw[:100]}")
    except Exception as e:
        logger.warning(f"HTTP 翻译失败: {e}")
    return ""


def translate_to_english(text: str, llm=None) -> str:
    """中文→英文翻译（LLM 优先，HTTP API 兜底）"""
    if not text:
        return ""
    # 简单回退：如果已经是英文直接返回
    if all(ord(c) < 128 for c in text):
        return text
    # 缓存命中
    if text in _translate_cache:
        return _translate_cache[text]
    # 1. 优先用 LLM
    if llm:
        try:
            result = llm.chat(f"Translate to English, output only the translation: {text}",
                              system="You are a professional translator.")
            if result and result.strip():
                translated = result.strip()
                _cache_set(text, translated)
                return translated
        except Exception as e:
            logger.warning(f"LLM translation failed: {e}")
    # 2. 兜底：HTTP 翻译接口
    result = _http_translate(text)
    if result:
        return result
    # 3. 都失败了返回原文
    logger.warning(f"翻译全部失败，中文描述将原样传入 ComfyUI（可能无效）: {text[:50]}...")
    return text
