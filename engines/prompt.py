"""Prompt 工程引擎 — LLM 生成模型友好 prompt + ComfyUI Prompt 构建"""
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
#  LLM 生成模型友好 prompt（prepare 阶段调用）
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

示例：
输入：22岁温柔女生，长发及腰，皮肤白皙，大眼睛，瓜子脸，身材娇小
输出：1girl, 22 years old, gentle appearance, long hair reaching waist, fair skin, big eyes, oval face, petite figure, delicate features

输入：25岁冷酷男生，短发，剑眉星目，高鼻梁，身材高挑，肌肉线条分明
输出：1boy, 25 years old, cold expression, short hair, thick straight eyebrows, bright eyes, high nose bridge, tall and slender, muscular build

只输出英文 prompt，不要任何解释。"""


_VIEW_PROMPT_SYSTEM = """你是一位顶级 AI 绘画提示词工程师。根据角色的完整外貌描述，为三个不同视角生成英文 prompt。

规则：
1. 只描述该视角**可见**的内容，不可见的特征必须省略
2. 正面（front）：包含面部特征、表情、发型正面、全身服装、配饰
3. 侧面（side）：侧面轮廓、发型侧面、体型剪影、服装侧面，可保留鼻梁/下巴轮廓
4. 背面（back）：只包含后脑勺/发型背面、背部、体型背面、服装背面、手臂/手部。**绝对不能包含任何面部特征**
5. 输出纯英文，逗号分隔的短语，不要完整句子
6. 保持原始描述的风格基调

输出格式（严格 JSON，不要其他文字）：
```json
{
  "front": "1girl, ...",
  "side": "1girl, ...",
  "back": "1girl, ..."
}
```"""


def generate_appearance_prompt(appearance_zh: str, llm) -> str:
    """用 LLM 将中文外貌描述转为模型友好的英文 prompt

    Args:
        appearance_zh: 中文外貌描述
        llm: LLM 后端实例

    Returns:
        英文 prompt 字符串，失败返回空字符串
    """
    if not appearance_zh or not llm:
        return ""
    # 已是英文直接返回
    if all(ord(c) < 128 for c in appearance_zh):
        return appearance_zh

    try:
        result = llm.chat(f"角色外貌描述：\n{appearance_zh}", system=_APPEARANCE_PROMPT_SYSTEM, max_tokens=512)
        if result and result.strip():
            prompt = result.strip().strip('"\'')
            logger.info(f"  ✅ 外貌 prompt 生成: {prompt[:80]}...")
            return prompt
    except Exception as e:
        logger.warning(f"外貌 prompt 生成失败: {e}")

    return ""


def generate_view_prompts(appearance_zh: str, llm) -> dict[str, str]:
    """用 LLM 将外貌描述拆分为三个视角的模型友好英文 prompt

    Args:
        appearance_zh: 中文外貌描述
        llm: LLM 后端实例

    Returns:
        {"front": "...", "side": "...", "back": "..."} 或空 dict（失败时）
    """
    if not appearance_zh or not llm:
        return {}

    prompt = f"角色外貌描述：\n{appearance_zh}\n\n请拆分为三个视角的英文 prompt。"

    try:
        from infra.json_parse import parse_llm_json
        response = llm.chat(prompt, system=_VIEW_PROMPT_SYSTEM, max_tokens=1024)
        result = parse_llm_json(response)
        if isinstance(result, dict) and all(k in result for k in ("front", "side", "back")):
            return {k: v.strip() for k, v in result.items() if isinstance(v, str)}
        logger.warning(f"LLM 视角拆分返回格式不正确: {response[:200]}")
    except Exception as e:
        logger.warning(f"LLM 视角拆分失败: {e}")

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

    # 优先视角专属 prompt
    view_prompt = char.get(f"appearance_{view_key}_prompt_en", "")
    if view_prompt:
        return view_prompt

    # 回退到通用 prompt
    return char.get("appearance_prompt_en", "")


def build_prompt(shot: dict, character_desc: str = "", scene_desc: str = "",
                 style: str = "cinematic", genre: str = "urban",
                 llm=None) -> str:
    """从镜头数据构建 ComfyUI Prompt

    character_desc 应为已准备好的英文 prompt（prepare 阶段生成的 appearance_prompt_en）。
    """
    parts = []

    # 风格前缀
    if style:
        parts.append(f"{style} style")
    if genre:
        parts.append(f"{genre} atmosphere")

    # 场景（已是英文则直接用，否则翻译）
    if scene_desc:
        if any(ord(c) > 127 for c in scene_desc):
            scene_desc = translate_to_english(scene_desc, llm=llm)
        parts.append(scene_desc)

    # 角色（调用方应传入 prompt_en，此处直接使用）
    if character_desc:
        parts.append(character_desc)

    # 动作：优先读预翻译的 action_en，否则翻译 action
    action = shot.get("action_en", "").strip()
    if not action:
        action = shot.get("action", "")
        if action:
            action = _strip_dialogue(action)
            if any(ord(c) > 127 for c in action):
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


# ══════════════════════════════════════════════════════════
#  翻译（场景描述、动作、台词等非外貌文本）
# ══════════════════════════════════════════════════════════

_TRANSLATE_API = "https://shanhe.kim/api/fany/fanyi.php"
_translate_cache: dict[str, str] = {}
_translate_cache_lock = __import__("threading").Lock()
_CACHE_MAX_SIZE = 4096


def _cache_set(key: str, value: str) -> None:
    with _translate_cache_lock:
        if len(_translate_cache) >= _CACHE_MAX_SIZE:
            evict_count = _CACHE_MAX_SIZE // 4
            for old_key in list(_translate_cache)[:evict_count]:
                del _translate_cache[old_key]
        _translate_cache[key] = value


def _http_translate(text: str) -> str:
    """通过山河翻译 API 进行中→英翻译（带缓存 + 重试）"""
    with _translate_cache_lock:
        if text in _translate_cache:
            return _translate_cache[text]
    import time as _time
    try:
        import httpx
        _do_http = lambda url: httpx.get(url, timeout=10, follow_redirects=True).text
    except ImportError:
        _do_http = lambda url: urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "ai-drama-pipeline/2.0"}),
            timeout=10).read().decode("utf-8", errors="replace")

    for attempt in range(3):
        try:
            url = f"{_TRANSLATE_API}?msg={urllib.parse.quote(text)}"
            raw = _do_http(url)
            m = re.search(r"结果[：:]\s*(.+)", raw, re.DOTALL)
            if m:
                result = m.group(1).strip()
                result = re.sub(r"<[^>]+>", "", result).strip()
                if result:
                    _cache_set(text, result)
                    logger.debug(f"HTTP 翻译成功: {text[:30]} → {result[:30]}")
                    return result
            logger.warning(f"HTTP 翻译返回格式异常: {raw[:100]}")
        except Exception as e:
            if attempt < 2:
                _time.sleep(0.5 * (attempt + 1))
                logger.debug(f"HTTP 翻译重试 ({attempt+1}/3): {e}")
            else:
                logger.warning(f"HTTP 翻译失败（已重试3次）: {e}")
    return ""


def translate_to_english(text: str, llm=None) -> str:
    """中文→英文翻译（LLM 优先，HTTP API 兜底）"""
    if not text:
        return ""
    if all(ord(c) < 128 for c in text):
        return text
    if text in _translate_cache:
        return _translate_cache[text]
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
    result = _http_translate(text)
    if result:
        return result
    logger.warning(f"翻译全部失败，中文描述将原样传入 ComfyUI（可能无效）: {text[:50]}...")
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
        elif t in _translate_cache:
            results[i] = _translate_cache[t]
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
                _cache_set(orig_text, translated)
                results[orig_idx] = translated
            else:
                logger.debug(f"批量翻译第 {i+1} 条解析失败，回退单条翻译")
                results[orig_idx] = translate_to_english(orig_text, llm=llm)

        logger.debug(f"批量翻译成功: {len(batch)} 条, 解析到 {len(parsed)} 条")

    except Exception as e:
        logger.warning(f"批量翻译失败，回退单条翻译: {e}")
        for orig_idx, orig_text in batch:
            results[orig_idx] = translate_to_english(orig_text, llm=llm)
