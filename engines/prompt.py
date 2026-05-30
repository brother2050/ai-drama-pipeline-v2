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
    #    [着道了]? 覆盖"嘟囔着：""喊道：""说了："等常见后缀
    text = re.sub(r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])[着道了]?\s*[：:]\s*[""「].*?[""」]', '', text)
    # 兜底：说：后面无引号的短对话（最多30字符到逗号/句号）
    text = re.sub(r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])[着道了]?\s*[：:]\s*[^，。,.]{0,30}[，。,.]?\s*', '', text)
    # 2. 先处理英文 says: 后的引号对话内容（保留后续动作）
    _SPEECH = r'(?:says?|said|asks?|asked|answers?|answered|replies?|replied|shouts?|shouted|yells?|yelled|whispers?|whispered|mutters?|muttered|screams?|screamed|cries?|cried|exclaims?|exclaimed|responds?|responded|states?|stated|remarks?|remarked|calls?|called|begs?|begged|pleads?|pleaded|demands?|demanded|insists?|insisted|suggests?|suggested)'
    # [:：] 同时匹配英文冒号和中文冒号
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*"[^"]*"', '', text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{_SPEECH}\s*[:：]\s*'[^']*'", '', text, flags=re.IGNORECASE)
    # 3. 移除 says: 后面无引号的短内容（对话）
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*[^,.]{{0,30}}[,.]?\s*', ' ', text, flags=re.IGNORECASE)
    # 4. 最后才移除残留的引号内容（中文引号）
    text = re.sub(r'[""「『].*?[""」』]', '', text)
    # 5. 移除残留的英文引号内容
    text = re.sub(r'"[^"]*"', '', text)
    text = re.sub(r"'[^']*'", '', text)
    # 清理多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── 视角感知的外貌描述拆分 ──

_VIEW_SPLIT_SYSTEM = """你是一位专业的 AI 绘画提示词工程师。根据用户提供的角色外貌描述，为三个不同视角生成英文提示词。

规则：
1. 只描述该视角**可见**的内容，不可见的特征必须省略
2. 正面（front）：包含面部特征、表情、发型正面、全身服装、配饰
3. 侧面（side）：侧面轮廓、发型侧面、体型剪影、服装侧面，可保留鼻梁/下巴轮廓
4. 背面（back）：只包含后脑勺/发型背面、背部、体型背面、服装背面、手臂/手部。**绝对不能包含任何面部特征**
5. 输出纯英文，逗号分隔的短语，不要完整句子
6. 保持原始描述的风格基调（病态/活力/冷酷等）

输出格式（严格 JSON，不要其他文字）：
```json
{
  "front": "...",
  "side": "...",
  "back": "..."
}
```"""


def generate_view_prompts(appearance_zh: str, llm) -> dict[str, str]:
    """用 LLM 将外貌描述拆分为三个视角的英文提示词

    Args:
        appearance_zh: 中文外貌描述
        llm: LLM 后端实例

    Returns:
        {"front": "...", "side": "...", "back": "..."} 或空 dict（失败时）
    """
    if not appearance_zh or not llm:
        return {}

    prompt = f"角色外貌描述：\n{appearance_zh}\n\n请拆分为三个视角的英文提示词。"

    try:
        from infra.json_parse import parse_llm_json
        response = llm.chat(prompt, system=_VIEW_SPLIT_SYSTEM)
        result = parse_llm_json(response)
        if isinstance(result, dict) and all(k in result for k in ("front", "side", "back")):
            return {k: v.strip() for k, v in result.items() if isinstance(v, str)}
        logger.warning(f"LLM 视角拆分返回格式不正确: {response[:200]}")
    except Exception as e:
        logger.warning(f"LLM 视角拆分失败: {e}")

    return {}


def get_view_appearance(char: dict, shot_type: str) -> str:
    """获取角色在指定视角的英文外貌描述

    仅从 YAML 读取预生成的视角专属描述，无则返回空字符串。
    新角色必须先运行 prepare 阶段生成视角描述。

    Args:
        char: 角色数据 dict
        shot_type: 景别（特写/侧面特写/背面特写/全身 等）

    Returns:
        英文外貌描述字符串，无则返回空字符串
    """
    if "背面" in shot_type:
        view_key = "back"
    elif "侧面" in shot_type:
        view_key = "side"
    else:
        view_key = "front"

    return char.get(f"appearance_{view_key}_en", "")


def build_prompt(shot: dict, character_desc: str = "", scene_desc: str = "",
                 style: str = "cinematic", genre: str = "urban",
                 llm=None) -> str:
    """从镜头数据构建 ComfyUI Prompt

    如果 character_desc / scene_desc 已经是英文（预翻译），直接使用，不调用 LLM。
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

    # 角色（已是英文则直接用，否则用专用翻译）
    if character_desc:
        if any(ord(c) > 127 for c in character_desc):
            character_desc = translate_appearance(character_desc)
            # 映射不足时回退到通用翻译
            if any(ord(c) > 127 for c in character_desc):
                character_desc = translate_to_english(character_desc, llm=llm)
        parts.append(character_desc)

    # 动作：优先读预翻译的 action_en，否则翻译 action
    action = shot.get("action_en", "").strip()
    if not action:
        action = shot.get("action", "")
        if action:
            action = _strip_dialogue(action)
            # 仅当有中文时才翻译（准备阶段已翻译则不会走到这里）
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


# 常见中文外貌描述→英文映射（兜底用，覆盖常见词）
_TRANSLATE_API = "https://shanhe.kim/api/fany/fanyi.php"

# 中文外貌特征 → AI 绘图模型友好英文映射
_APPEARANCE_MAP = {
    # 年龄/性别
    "年轻女性": "1girl, young woman",
    "年轻男性": "1boy, young man",
    "少女": "1girl, teenage girl",
    "少年": "1boy, teenage boy",
    "成年女性": "1woman, adult woman",
    "成年男性": "1man, adult man",
    # 发型
    "长发": "long hair",
    "短发": "short hair",
    "中长发": "medium-length hair",
    "及肩长发": "shoulder-length hair",
    "长发及肩": "shoulder-length hair",
    "马尾": "ponytail",
    "双马尾": "twintails",
    "丸子头": "messy bun",
    "卷发": "curly hair",
    "直发": "straight hair",
    "刘海": "bangs",
    "齐刘海": "blunt bangs",
    "侧分刘海": "side-swept bangs",
    "黑色头发": "black hair",
    "棕色头发": "brown hair",
    "金色头发": "blonde hair",
    "红色头发": "red hair",
    "白色头发": "white hair",
    "银色头发": "silver hair",
    "粉色头发": "pink hair",
    "蓝色头发": "blue hair",
    "渐变色头发": "gradient hair",
    # 五官
    "大眼睛": "big eyes, detailed eyes",
    "小眼睛": "small eyes",
    "丹凤眼": "almond-shaped eyes",
    "杏眼": "round eyes",
    "柳叶眉": "thin arched eyebrows",
    "剑眉": "thick straight eyebrows",
    "浓眉": "thick eyebrows",
    "高鼻梁": "high nose bridge",
    "挺鼻": "straight nose",
    "薄唇": "thin lips",
    "厚唇": "full lips",
    "樱桃小嘴": "small rosy lips",
    "瓜子脸": "oval face, V-shaped face",
    "圆脸": "round face",
    "方脸": "square face",
    "鹅蛋脸": "oval face",
    "酒窝": "dimples",
    "美人痣": "beauty mark",
    # 体型
    "体型偏瘦": "slender, slim body",
    "体型匀称": "athletic build, well-proportioned",
    "体型丰满": "curvy body",
    "身材高挑": "tall and slender",
    "娇小": "petite",
    "肌肉发达": "muscular",
    # 肤色
    "皮肤白皙": "fair skin, light skin",
    "皮肤黝黑": "tanned skin, dark skin",
    "小麦色皮肤": "olive skin, warm skin tone",
    # 配饰
    "戴眼镜": "wearing glasses",
    "戴帽子": "wearing hat",
    "戴耳环": "wearing earrings",
    "戴项链": "wearing necklace",
    "纹身": "tattoo",
    "雀斑": "freckles",
}

# 性别标记，用于自动添加触发词
_GENDER_MARKERS = {
    "女性": "1girl", "女": "1girl", "woman": "1girl", "girl": "1girl", "female": "1girl",
    "男性": "1boy", "男": "1boy", "man": "1boy", "boy": "1boy", "male": "1boy",
}
_translate_cache: dict[str, str] = {}


def translate_appearance(chinese_desc: str) -> str:
    """将中文外貌描述转为 AI 绘图模型友好的英文 prompt

    不是字面翻译，而是按 Stable Diffusion / Flux / Cosmos 的 prompt 格式重组。
    优先查本地映射表，剩余部分用 LLM 或 HTTP 翻译兜底。

    Args:
        chinese_desc: 中文外貌描述

    Returns:
        英文 prompt 字符串，逗号分隔的短语
    """
    if not chinese_desc:
        return ""
    # 已是英文直接返回
    if all(ord(c) < 128 for c in chinese_desc):
        return chinese_desc

    result_parts = []
    remaining = chinese_desc

    # 1. 从描述中提取性别标记（添加到最前面）
    gender_added = False
    gender_span: tuple[int, int] | None = None
    for zh, en in _GENDER_MARKERS.items():
        idx = remaining.find(zh)
        if idx >= 0:
            result_parts.append(en)
            gender_added = True
            gender_span = (idx, idx + len(zh))
            break

    # 2. 逐个匹配映射表（按长度降序，避免短词误匹配长词）
    sorted_keys = sorted(_APPEARANCE_MAP.keys(), key=len, reverse=True)
    matched_spans: list[tuple[int, int]] = []
    if gender_span:
        matched_spans.append(gender_span)

    for zh_key in sorted_keys:
        idx = remaining.find(zh_key)
        if idx >= 0:
            # 跳过与性别标记重复的项
            en_val = _APPEARANCE_MAP[zh_key]
            if gender_added and en_val in ("1girl", "1boy", "1woman", "1man"):
                continue
            # 检查是否与已匹配区域重叠或被包含
            end = idx + len(zh_key)
            overlap = False
            for ms, me in matched_spans:
                # 完全包含或重叠
                if (idx >= ms and end <= me) or (idx < me and end > ms):
                    overlap = True
                    break
            if not overlap:
                result_parts.append(en_val)
                matched_spans.append((idx, end))

    # 3. 提取未匹配的数字信息（如 "22岁", "165cm", "180cm"）
    import re
    for m in re.finditer(r'(\d+)\s*(岁|cm|米|m)', remaining):
        start, end = m.span()
        overlap = any(not (end <= ms or start >= me) for ms, me in matched_spans)
        if not overlap:
            num = m.group(1)
            unit = m.group(2)
            if unit == "岁":
                result_parts.append(f"{num} years old")
            elif unit in ("cm", "米", "m"):
                result_parts.append(f"{num}cm tall")
            matched_spans.append((start, end))

    # 4. 如果映射表覆盖了大部分内容，直接用映射结果
    matched_len = sum(me - ms for ms, me in matched_spans)
    total_len = len(remaining)

    if matched_len / max(total_len, 1) > 0.5:
        # 映射覆盖超过 50%，用映射结果
        return ", ".join(result_parts)

    # 5. 映射覆盖不足，回退到 LLM/HTTP 翻译
    return chinese_desc  # 交给调用方的 translate_to_english 处理



_translate_cache_lock = __import__("threading").Lock()
_CACHE_MAX_SIZE = 4096


def _cache_set(key: str, value: str) -> None:
    with _translate_cache_lock:
        if len(_translate_cache) >= _CACHE_MAX_SIZE:
            # 淘汰最早插入的一批条目（FIFO 近似），避免 clear() 导致缓存雪崩
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


_BATCH_TRANSLATE_SYSTEM = """You are a professional translator. The user will send numbered Chinese texts.
Translate each to English. Output ONLY the translations, one per line, keeping the same numbering.
Do not add explanations. If a line is already English, output it unchanged."""

_BATCH_MAX_CHARS = 4000  # 单批最大字符数，避免超 context


def batch_translate_to_english(texts: list[str], llm=None) -> list[str]:
    """批量中→英翻译（一次 LLM 调用翻译多条文本）

    Args:
        texts: 待翻译文本列表
        llm: LLM 后端实例

    Returns:
        与 texts 等长的翻译结果列表。单条翻译失败时回退到 translate_to_english。
    """
    if not llm:
        return [translate_to_english(t, llm=None) for t in texts]

    # 分离：需要翻译的 vs 已是英文/空的
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

    # 按字符数分批，避免超 context
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
    # 构建编号 prompt
    lines = [f"{i + 1}. {text}" for i, (_, text) in enumerate(batch)]
    prompt = "\n".join(lines)

    try:
        response = llm.chat(prompt, system=_BATCH_TRANSLATE_SYSTEM)
        if not response or not response.strip():
            raise ValueError("LLM 返回空")

        # 解析：按行匹配 "数字. 翻译" 或 "数字) 翻译"
        parsed: dict[int, str] = {}
        for line in response.strip().splitlines():
            line = line.strip()
            m = re.match(r"^(\d+)\s*[.)]\s*(.+)", line)
            if m:
                parsed[int(m.group(1))] = m.group(2).strip()

        # 回填结果
        for i, (orig_idx, orig_text) in enumerate(batch):
            translated = parsed.get(i + 1, "")
            if translated:
                _cache_set(orig_text, translated)
                results[orig_idx] = translated
            else:
                # 解析失败，单条回退
                logger.debug(f"批量翻译第 {i+1} 条解析失败，回退单条翻译")
                results[orig_idx] = translate_to_english(orig_text, llm=llm)

        logger.debug(f"批量翻译成功: {len(batch)} 条, 解析到 {len(parsed)} 条")

    except Exception as e:
        # 整批失败，全部回退到单条翻译
        logger.warning(f"批量翻译失败，回退单条翻译: {e}")
        for orig_idx, orig_text in batch:
            results[orig_idx] = translate_to_english(orig_text, llm=llm)
