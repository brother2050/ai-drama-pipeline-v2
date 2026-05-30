"""Prompt 工程引擎 — LLM 批量生成模型友好 prompt + ComfyUI Prompt 构建"""
from __future__ import annotations
import logging
import re

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
    "特写": "extreme close-up shot, detailed face, looking at viewer",
    "近景": "close-up shot, head and shoulders",
    "中景": "medium shot, waist up",
    "过肩": "over-the-shoulder shot",
    "全身": "full body shot",
    "全景": "wide shot, full scene",
    "远景": "extreme wide shot, establishing shot",
    "双人全景": "two-shot, both characters visible",
    "侧面特写": "side profile close-up shot, detailed side view of face, looking left, from the side",
    "背面特写": "back view close-up shot, seen from behind, back of head, facing away from viewer",
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
    """清理 action 中的对话/台词内容，防止模型将文字渲染进画面"""
    if not text:
        return text
    text = re.sub(r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])[着道了]?\s*[：:]\s*[""「].*?[""」]', '', text)
    text = re.sub(r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])[着道了]?\s*[：:]\s*[^，。,.]{0,30}[，。,.]?\s*', '', text)
    _SPEECH = r'(?:says?|said|asks?|asked|answers?|answered|replies?|replied|shouts?|shouted|yells?|yelled|whispers?|whispered|mutters?|muttered|screams?|screamed|cries?|cried|exclaims?|exclaimed|responds?|responded|states?|stated|remarks?|remarked|calls?|called|begs?|begged|pleads?|pleaded|demands?|demanded|insists?|insisted|suggests?|suggested)'
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*"[^"]*"', '', text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{_SPEECH}\s*[:：]\s*'[^']*'", '', text, flags=re.IGNORECASE)
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*[^,.]{{0,30}}[,.]?\s*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'[""「『].*?[""」』]', '', text)
    text = re.sub(r'"[^"]*"', '', text)
    text = re.sub(r"'[^']*'", '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ══════════════════════════════════════════════════════════
#  LLM 批量生成模型友好 prompt（prepare 阶段调用）
# ══════════════════════════════════════════════════════════

_APPEARANCE_PROMPT_SYSTEM = """你是一位顶级 AI 绘画提示词工程师，精通 Stable Diffusion / Flux / Cosmos 的 prompt 编写。

根据用户提供的中文角色外貌描述，生成可直接用于 AI 绘图的英文 prompt。

规则：
1. 输出纯英文，逗号分隔的短语，不要完整句子
2. 顺序：性别标记 → 年龄 → 面部特征 → 发型 → 体型 → 肤色 → 服装 → 配饰 → 气质/风格
3. 使用 AI 绘图模型识别率高的关键词（如 1girl, 1boy, long hair, fair skin）
4. 保留所有外貌细节，不遗漏、不添加原文没有的信息
5. 不要包含动作、场景、情绪、镜头信息（这些由其他模块处理）
6. 不要包含 quality 标签（如 best quality, masterpiece，由负向 prompt 控制）
7. 如果描述中有年龄、身高等数字信息，保留

输出格式（严格 JSON，不要其他文字）：
```json
{
  "prompt_en": "1girl, 22 years old, ...",
  "front": "1girl, 22 years old, ...（正面可见的所有特征）",
  "side": "1girl, ...（侧面可见特征，无正面面部细节）",
  "back": "1girl, ...（仅背面可见特征，绝对无面部）"
}
```

视角规则：
- front：包含面部特征、表情、发型正面、全身服装、配饰
- side：侧面轮廓、发型侧面、体型剪影、服装侧面，可保留鼻梁/下巴轮廓
- back：只包含后脑勺/发型背面、背部、体型背面、服装背面。**绝对不能包含任何面部特征**

只输出 JSON，不要任何解释。"""


def batch_generate_appearance_prompts(characters: list[dict], llm) -> dict[str, dict]:
    """批量生成角色模型友好 prompt（自动分批，按模型上下文动态调整）

    自动估算每个角色的 token 开销，按模型可用上下文分批处理。
    每批调用一次 LLM，结果合并返回。

    Args:
        characters: 角色数据列表，每项需有 id 和 appearance 字段
        llm: LLM 后端实例

    Returns:
        {char_id: {"prompt_en": "...", "front": "...", "side": "...", "back": "..."}} 映射
    """
    if not characters or not llm:
        return {}

    # 估算模型上下文长度（优先读配置，兜底 32K）
    max_ctx = _estimate_context_length(llm)
    # 系统 prompt + 输出预留
    system_overhead = 800
    output_reserve = 2000  # 每批输出预留
    available = max_ctx - system_overhead - output_reserve

    # 按字符数分批（中文字符 ≈ 2 tokens，留余量按 3 算）
    batches: list[list[dict]] = [[]]
    batch_tokens = 0
    for char in characters:
        appearance = char.get("appearance", "")
        char_tokens = len(appearance) * 3 + 200  # 描述 + id + 结构开销
        if batch_tokens + char_tokens > available and batches[-1]:
            batches.append([])
            batch_tokens = 0
        batches[-1].append(char)
        batch_tokens += char_tokens

    if len(batches) > 1:
        logger.info(f"  角色 prompt 分批处理: {len(characters)} 个角色 → {len(batches)} 批")

    # 逐批调用 LLM
    all_mapping: dict[str, dict] = {}
    for batch_idx, batch in enumerate(batches):
        mapping = _generate_prompt_batch(batch, llm)
        all_mapping.update(mapping)
        if len(batches) > 1:
            logger.info(f"  批次 {batch_idx + 1}/{len(batches)}: {len(mapping)} 个角色完成")

    logger.info(f"  ✅ 批量 prompt 生成: {len(all_mapping)}/{len(characters)} 个角色")
    return all_mapping


def _estimate_context_length(llm) -> int:
    """估算 LLM 可用上下文长度

    优先级：
    1. llm.context_length 属性（后端自动检测 / 按模型名猜）
    2. 兜底 8K（保守，宁可多分批也别炸）
    """
    val = getattr(llm, "context_length", None)
    if val and isinstance(val, int) and val > 0:
        return val

    return 8192


def _generate_prompt_batch(characters: list[dict], llm) -> dict[str, dict]:
    """处理单批角色 prompt 生成"""
    parts = []
    for i, char in enumerate(characters):
        cid = char.get("id", f"char_{i}")
        appearance = char.get("appearance", "")
        parts.append(f"[角色 {i+1}] id={cid}\n外貌描述：{appearance}")

    prompt = "请为以下每个角色生成 AI 绘图 prompt，按角色编号输出 JSON 数组。\n\n" + "\n\n".join(parts)

    try:
        from infra.json_parse import parse_llm_json
        response = llm.chat(prompt, system=_APPEARANCE_PROMPT_SYSTEM, max_tokens=4096)
        result = parse_llm_json(response)

        if not result:
            logger.warning(f"批量 prompt 生成返回无法解析")
            return {}

        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list):
            return {}

        mapping: dict[str, dict] = {}
        for i, item in enumerate(result):
            if not isinstance(item, dict):
                continue
            cid = item.get("id", "")
            if not cid and i < len(characters):
                cid = characters[i].get("id", f"char_{i}")
            if cid:
                mapping[cid] = {
                    "prompt_en": item.get("prompt_en", ""),
                    "front": item.get("front", ""),
                    "side": item.get("side", ""),
                    "back": item.get("back", ""),
                }
        return mapping

    except Exception as e:
        logger.warning(f"批量 prompt 生成失败: {e}")
        return {}


def get_view_appearance(char: dict, shot_type: str) -> str:
    """获取角色在指定视角的模型友好英文 prompt

    优先读 appearance_{view}_prompt_en（prepare 阶段 LLM 生成），
    无则回退到 appearance_prompt_en（通用 prompt）。

    Args:
        char: 角色数据 dict
        shot_type: 景别（特写/侧面特写/背面特写/全身 等）

    Returns:
        英文 prompt 字符串
    """
    if "背面" in shot_type:
        view_key = "back"
    elif "侧面" in shot_type:
        view_key = "side"
    else:
        view_key = "front"

    view_prompt = char.get(f"appearance_{view_key}_prompt_en", "")
    if view_prompt:
        return view_prompt

    return char.get("appearance_prompt_en", "")


def build_prompt(shot: dict, character_desc: str = "", scene_desc: str = "",
                 style: str = "cinematic", genre: str = "urban") -> str:
    """从镜头数据构建 ComfyUI Prompt

    character_desc 应为已准备好的英文 prompt（prepare 阶段生成的 appearance_prompt_en）。
    """
    parts = []

    if style:
        parts.append(f"{style} style")
    if genre:
        parts.append(f"{genre} atmosphere")

    if scene_desc:
        if any(ord(c) > 127 for c in scene_desc):
            logger.warning(f"场景描述仍为中文，请先执行: drama prepare <集数>")
        parts.append(scene_desc)

    if character_desc:
        parts.append(character_desc)

    action = shot.get("action_en", "").strip()
    if not action:
        action = shot.get("action", "")
        if action:
            action = _strip_dialogue(action)
            if any(ord(c) > 127 for c in action):
                logger.warning(f"动作描述仍为中文（action_en 缺失），请先执行: drama prepare <集数>")
    else:
        action = _strip_dialogue(action)
    if action:
        parts.append(action)

    emotion = shot.get("emotion", "neutral")
    emotion_desc = EMOTION_MAP.get(emotion, EMOTION_MAP.get("neutral", "neutral expression"))
    parts.append(emotion_desc)

    shot_type = shot.get("shot_type", "中景")
    parts.append(SHOT_TYPE_MAP.get(shot_type, "medium shot"))

    camera = shot.get("camera", "固定")
    parts.append(CAMERA_MAP.get(camera, "static camera"))

    return ", ".join(parts)


# ══════════════════════════════════════════════════════════
#  LLM 翻译（场景、动作、台词等非外貌文本）
# ══════════════════════════════════════════════════════════

_TRANSLATE_SYSTEM = "You are a professional translator. Output only the translation, no explanations."


def translate_to_english(text: str, llm=None) -> str:
    """中文→英文翻译（LLM）"""
    if not text:
        return ""
    if all(ord(c) < 128 for c in text):
        return text
    if not llm:
        logger.warning(f"LLM 不可用，中文描述将原样传入（可能无效）: {text[:50]}...")
        return text
    try:
        result = llm.chat(f"Translate to English: {text}", system=_TRANSLATE_SYSTEM)
        return result.strip() if result and result.strip() else text
    except Exception as e:
        logger.warning(f"翻译失败: {e}")
        return text


_BATCH_TRANSLATE_SYSTEM = """You are a professional translator. The user will send numbered Chinese texts.
Translate each to English. Output ONLY the translations, one per line, keeping the same numbering.
Do not add explanations. If a line is already English, output it unchanged."""

_BATCH_MAX_CHARS = 4000


def batch_translate_to_english(texts: list[str], llm=None) -> list[str]:
    """批量中→英翻译（一次 LLM 调用翻译多条文本）"""
    if not llm:
        return [translate_to_english(t, llm=None) for t in texts]

    need_idx: list[int] = []
    need_text: list[str] = []
    results: list[str] = [""] * len(texts)

    for i, t in enumerate(texts):
        if not t:
            results[i] = ""
        elif all(ord(c) < 128 for c in t):
            results[i] = t
        else:
            need_idx.append(i)
            need_text.append(t)

    if not need_text:
        return results

    batches: list[list[tuple[int, str]]] = [[]]
    batch_chars = 0
    for idx, text in zip(need_idx, need_text):
        if batch_chars + len(text) > _BATCH_MAX_CHARS and batches[-1]:
            batches.append([])
            batch_chars = 0
        batches[-1].append((idx, text))
        batch_chars += len(text)

    for batch in batches:
        _translate_batch(batch, results, llm)

    return results


def _translate_batch(batch: list[tuple[int, str]], results: list[str], llm) -> None:
    """翻译一批文本，结果写入 results 对应位置"""
    lines = [f"{i + 1}. {text}" for i, (_, text) in enumerate(batch)]
    prompt = "\n".join(lines)

    try:
        response = llm.chat(prompt, system=_BATCH_TRANSLATE_SYSTEM)
        if not response or not response.strip():
            raise ValueError("LLM 返回空")

        parsed: dict[int, str] = {}
        for line in response.strip().splitlines():
            line = line.strip()
            m = re.match(r"^(\d+)\s*[.)]\s*(.+)", line)
            if m:
                parsed[int(m.group(1))] = m.group(2).strip()

        for i, (orig_idx, orig_text) in enumerate(batch):
            translated = parsed.get(i + 1, "")
            if translated:
                results[orig_idx] = translated
            else:
                results[orig_idx] = translate_to_english(orig_text, llm=llm)

        logger.debug(f"批量翻译成功: {len(batch)} 条, 解析到 {len(parsed)} 条")

    except Exception as e:
        logger.warning(f"批量翻译失败，回退单条翻译: {e}")
        for orig_idx, orig_text in batch:
            results[orig_idx] = translate_to_english(orig_text, llm=llm)
