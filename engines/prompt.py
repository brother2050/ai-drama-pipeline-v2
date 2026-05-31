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
    """清理 action 中的对话/台词内容，防止模型将文字渲染进画面

    只清理紧跟对话动词的引号内容（说/道/喊/问/答/叫 等），
    保留场景道具上的文字描述（如墙上"欢迎光临"、杯子上"Best Day Ever"）。
    """
    if not text:
        return text
    # 英文对话动词 + 引号内容
    _SPEECH = r'(?:says?|said|asks?|asked|answers?|answered|replies?|replied|shouts?|shouted|yells?|yelled|whispers?|whispered|mutters?|muttered|screams?|screamed|cries?|cried|exclaims?|exclaimed|responds?|responded|states?|stated|remarks?|remarked|calls?|called|begs?|begged|pleads?|pleaded|demands?|demanded|insists?|insisted|suggests?|suggested)'
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*"[^"]*"', '', text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{_SPEECH}\s*[:：]\s*'[^']*'", '', text, flags=re.IGNORECASE)
    text = re.sub(rf'\b{_SPEECH}\s*[:：]\s*[^,.]{{0,30}}[,.]?\s*', ' ', text, flags=re.IGNORECASE)
    # 中文对话：冒号 + 引号内容（删除引号及内容），以及对话动词 + 直接引号
    text = re.sub(r'[：:]\s*[""「].*?[""」]', '', text)
    text = re.sub(r'[说喊道问答呼吼叫骂叹]\s*[""「].*?[""」]', '', text)
    # 中文对话动词 + 无引号短句（到逗号/句号截止）
    text = re.sub(
        r'(?:嘟囔|嘀咕|[说喊道问答呼吼叫骂叹])[着道了口气声]*\s*[：:]\s*[^，。,.]{0,30}[，。,.]?\s*',
        '', text)
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
8. 【重要】身体特征（伤疤、纹身、胎记、烧伤痕迹等）必须在所有可见该部位的视角中重复出现

输出格式（严格 JSON，不要其他文字）：
```json
{
  "prompt_en": "1girl, 22 years old, ...",
  "body_features": "cross scar on left cheek, burn mark on neck（所有身体特征集中列出，无则留空）",
  "front": "1girl, 22 years old, ...（正面可见的所有特征 + body_features 中正面可见的部分）",
  "left_side": "1girl, 22 years old, ...（左侧可见特征，含侧面轮廓 + body_features 中左侧可见的部分）",
  "right_side": "1girl, 22 years old, ...（右侧可见特征，含侧面轮廓 + body_features 中右侧可见的部分）",
  "back": "1girl, 22 years old, ...（仅背面可见特征 + body_features 中背面可见的部分）",
  "three_quarter": "1girl, 22 years old, ...（3/4侧面，最常用的美观视角，包含部分正面和侧面特征）"
}
```

视角规则：
- front：面部全部特征（眼睛、鼻子、嘴巴、眉毛、耳朵）、表情、发型正面、服装正面、配饰、身体特征（正面可见的伤疤/纹身等）
- left_side：左侧轮廓（额头线条、鼻梁、嘴唇轮廓、下巴线条、左耳）、左眼可见、发型侧面、体型剪影、服装侧面。身体特征：左侧可见的伤疤/纹身/胎记必须保留
- right_side：右侧轮廓（与 left_side 镜像）、右眼可见、发型侧面、服装侧面。身体特征：右侧可见的伤疤/纹身/胎记必须保留
- back：后脑发型、双耳背面、后颈、肩背体态、服装背面。不能包含眼睛、鼻子、嘴巴。身体特征：背部/后颈可见的伤疤/纹身必须保留
- three_quarter：3/4 侧面（最常用美观视角），包含一侧面部特征 + 部分正面特征，身体特征对应侧面保留

body_features 规则：
- 从原始描述中提取所有身体特征（伤疤、纹身、胎记、烧伤、残疾等）
- 标注位置（left cheek, neck, right arm, back 等）
- 每个视角 prompt 必须包含该视角可见的 body_features
- 如果原文没有身体特征，body_features 留空字符串"""


def batch_generate_appearance_prompts(characters: list[dict], llm) -> dict[str, dict]:
    """批量生成角色模型友好 prompt — 全部成功或抛异常

    设计原则：部分失败 = 全部失败。
    管线后续步骤（定妆照/首帧）依赖每个角色都有 prompt，缺一个就全部崩。
    所以要么全部生成成功，要么抛异常让调用方知道整个 prepare 失败了。

    策略：
    1. 按上下文长度自动分批，每批一次 LLM 调用
    2. 批次失败 → 重试 3 次（指数退避）
    3. 批次仍然失败 → 降级为逐角色生成（每个角色独立 LLM 调用，各重试 2 次）
    4. 单角色也失败 → 抛异常，报告哪些角色失败

    Args:
        characters: 角色数据列表，每项需有 id 和 appearance 字段
        llm: LLM 后端实例

    Returns:
        {char_id: {"prompt_en": "...", "front": "...", "side": "...", "back": "..."}} 映射

    Raises:
        RuntimeError: 有任何角色 prompt 生成最终失败时
    """
    if not characters or not llm:
        return {}

    import time as _time

    # 估算模型上下文长度
    max_ctx = _estimate_context_length(llm)
    system_overhead = 800
    output_reserve = 2000
    available = max_ctx - system_overhead - output_reserve

    # 按字符数分批
    batches: list[list[dict]] = [[]]
    batch_tokens = 0
    for char in characters:
        appearance = char.get("appearance", "")
        char_tokens = len(appearance) * 3 + 200
        if batch_tokens + char_tokens > available and batches[-1]:
            batches.append([])
            batch_tokens = 0
        batches[-1].append(char)
        batch_tokens += char_tokens

    if len(batches) > 1:
        logger.info(f"  角色 prompt 分批处理: {len(characters)} 个角色 → {len(batches)} 批")

    # 逐批调用（带重试）
    all_mapping: dict[str, dict] = {}
    failed_chars: list[dict] = []

    for batch_idx, batch in enumerate(batches):
        mapping = _generate_prompt_batch_with_retry(batch, llm, max_retries=3)
        all_mapping.update(mapping)

        batch_ids = {c.get("id", "") for c in batch}
        succeeded_ids = set(mapping.keys())
        for c in batch:
            if c.get("id", "") not in succeeded_ids:
                failed_chars.append(c)

        if len(batches) > 1:
            ok = len(batch) - len(batch_ids - succeeded_ids)
            logger.info(f"  批次 {batch_idx + 1}/{len(batches)}: {ok}/{len(batch)} 成功")

    # 降级：逐角色重试失败的角色
    if failed_chars:
        logger.warning(f"  批量生成失败 {len(failed_chars)} 个角色，降级为逐角色重试...")
        still_failed = []
        for char in failed_chars:
            cid = char.get("id", "?")
            mapping = _generate_prompt_batch_with_retry([char], llm, max_retries=2)
            if mapping:
                all_mapping.update(mapping)
                logger.info(f"  ✅ 逐角色重试成功: {cid}")
            else:
                still_failed.append(cid)

        if still_failed:
            raise RuntimeError(
                f"角色 prompt 生成失败（{len(still_failed)}/{len(characters)} 个）: "
                f"{', '.join(still_failed)}。请检查 LLM 服务后重试。"
            )

    logger.info(f"  ✅ 批量 prompt 生成完成: {len(all_mapping)}/{len(characters)} 个角色")
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


def _generate_prompt_batch_with_retry(characters: list[dict], llm, max_retries: int = 3) -> dict[str, dict]:
    """处理单批角色 prompt 生成（带指数退避重试）

    Args:
        characters: 角色数据列表
        llm: LLM 后端实例
        max_retries: 最大重试次数

    Returns:
        {char_id: {...}} 映射，失败时返回空 dict
    """
    import time as _time

    for attempt in range(max_retries):
        try:
            mapping = _generate_prompt_batch(characters, llm)
            if mapping:
                return mapping
            # 返回空可能是 LLM 输出解析失败，重试
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"  prompt 批次返回空（尝试 {attempt+1}/{max_retries}），{wait}s 后重试")
                _time.sleep(wait)
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"  prompt 批次失败（尝试 {attempt+1}/{max_retries}）: {e}，{wait}s 后重试")
                _time.sleep(wait)
            else:
                logger.error(f"  prompt 批次最终失败: {e}", exc_info=True)

    return {}


def _generate_prompt_batch(characters: list[dict], llm) -> dict[str, dict]:
    """处理单批角色 prompt 生成（单次调用）"""
    parts = []
    for i, char in enumerate(characters):
        cid = char.get("id", f"char_{i}")
        appearance = char.get("appearance", "")
        parts.append(f"[角色 {i+1}] id={cid}\n外貌描述：{appearance}")

    prompt = "请为以下每个角色生成 AI 绘图 prompt，按角色编号输出 JSON 数组。\n\n" + "\n\n".join(parts)

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
                "body_features": item.get("body_features", ""),
                "front": item.get("front", ""),
                "left_side": item.get("left_side", ""),
                "right_side": item.get("right_side", ""),
                "back": item.get("back", ""),
                "three_quarter": item.get("three_quarter", ""),
            }
    return mapping


def get_view_appearance(char: dict, shot_type: str) -> str:
    """获取角色在指定视角的模型友好英文 prompt

    优先读 appearance_{view}_prompt_en（prepare 阶段 LLM 生成），
    无则回退到 appearance_prompt_en（通用 prompt）。

    视角映射（5视图）：
    - 特写/近景/中景/全身/过肩 → front
    - 侧面特写 → left_side（默认左侧，无则 right_side，再无则 front）
    - 背面特写 → back
    - 3/4侧/三人全景 → three_quarter

    Args:
        char: 角色数据 dict
        shot_type: 景别（特写/侧面特写/背面特写/全身 等）

    Returns:
        英文 prompt 字符串
    """
    if "背面" in shot_type:
        view_key = "back"
    elif "侧面" in shot_type:
        # 优先 left_side，回退 right_side，最后 front
        view_key = "left_side"
    elif "3/4" in shot_type or "三人" in shot_type:
        view_key = "three_quarter"
    else:
        view_key = "front"

    # 尝试精确匹配
    view_prompt = char.get(f"appearance_{view_key}_prompt_en", "")
    if view_prompt:
        return view_prompt

    # 侧面回退：left_side → right_side
    if view_key in ("left_side", "right_side"):
        for fallback_key in ("right_side", "left_side"):
            fallback = char.get(f"appearance_{fallback_key}_prompt_en", "")
            if fallback:
                return fallback

    # 3/4 回退到 front
    if view_key == "three_quarter":
        front = char.get("appearance_front_prompt_en", "")
        if front:
            return front

    # 最终回退：通用 prompt
    return char.get("appearance_prompt_en", "")


def build_prompt(shot: dict, character_desc: str = "", scene_desc: str = "",
                 style: str = "cinematic", genre: str = "urban",
                 image_backend: str = "", registry=None) -> str:
    """从镜头数据构建 ComfyUI Prompt

    character_desc 应为已准备好的英文 prompt（prepare 阶段生成的 appearance_prompt_en）。

    Args:
        image_backend: 图像后端名（sd15/flux/cosmos/...）。prompt 风格从注册表查询。
        registry: ModelRegistry 实例（可选，不传则自动创建）
    """
    # ── 收集各维度素材（两种风格共用） ──
    style_tag = f"{style} style" if style else ""
    genre_tag = f"{genre} atmosphere" if genre else ""

    scene_clean = ""
    if scene_desc:
        if any(ord(c) > 127 for c in scene_desc):
            logger.warning(f"场景描述仍为中文，请先执行: drama prepare <集数>")
        scene_clean = scene_desc

    char_clean = character_desc.strip() if character_desc else ""

    action = shot.get("action_en", "").strip()
    if not action:
        action = shot.get("action", "")
        if action:
            action = _strip_dialogue(action)
            if any(ord(c) > 127 for c in action):
                logger.warning(f"动作描述仍为中文（action_en 缺失），请先执行: drama prepare <集数>")
    else:
        action = _strip_dialogue(action)

    emotion = shot.get("emotion", "neutral")
    emotion_desc = EMOTION_MAP.get(emotion, EMOTION_MAP.get("neutral", "neutral expression"))

    shot_type = shot.get("shot_type", "中景")
    shot_type_desc = SHOT_TYPE_MAP.get(shot_type, "medium shot")

    camera = shot.get("camera", "固定")
    camera_desc = CAMERA_MAP.get(camera, "static camera")

    # ── 判断后端 prompt 风格（从注册表查询，不硬编码后端名） ──
    if registry is None:
        from flow.model_registry import ModelRegistry
        from infra.config import resolve_project_config
        try:
            cfg_path = resolve_project_config()
        except FileNotFoundError:
            import os
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cfg_path = os.path.join(root, "config", "project.yaml")
        registry = ModelRegistry(cfg_path)

    prompt_style = registry.get_prompt_style(image_backend) if image_backend else "tag"

    if prompt_style == "natural":
        return _build_natural_prompt(
            style_tag, genre_tag, scene_clean, char_clean,
            action, emotion, emotion_desc, shot_type_desc, camera_desc)
    else:
        prompt = _build_tag_prompt(
            style_tag, genre_tag, scene_clean, char_clean,
            action, emotion_desc, shot_type_desc, camera_desc)
        # SD1.5 CLIP 最大 75 tokens（77 含 start/end），超长时按逗号截断
        prompt = _truncate_tag_prompt(prompt, max_tokens=75)
        return prompt


def _truncate_tag_prompt(prompt: str, max_tokens: int = 75) -> str:
    """将逗号分隔的 tag prompt 截断到指定 token 数以内。

    SD1.5 CLIP tokenizer 限制 75 tokens（不含 start/end token）。
    粗略估算：1 token ≈ 4 字符（英文），按逗号分隔的 tag 边界截断，
    保留前面的 tag（style/genre/scene/character 优先），丢弃末尾溢出部分。
    """
    # 粗略估算 token 数（英文约 4 字符/token，含逗号和空格）
    est_tokens = len(prompt) / 4
    if est_tokens <= max_tokens:
        return prompt

    # 按逗号拆分，逐个 tag 累加，超出限制时截断
    tags = [t.strip() for t in prompt.split(",") if t.strip()]
    result = []
    char_count = 0
    for tag in tags:
        # 估算新增 token：tag 字符数/4 + 1(逗号+空格)
        tag_cost = len(tag) / 4 + 1
        if char_count + tag_cost > max_tokens * 4:
            break
        result.append(tag)
        char_count += len(tag) + 2  # ", " = 2 chars

    truncated = ", ".join(result)
    if len(truncated) < len(prompt):
        logger.info(f"SD1.5 prompt 截断: {len(prompt)} → {len(truncated)} 字符 "
                    f"(保留 {len(result)}/{len(tags)} 个 tag)")
    return truncated


def _build_tag_prompt(style_tag: str, genre_tag: str, scene: str, character: str,
                      action: str, emotion_desc: str, shot_type: str, camera: str) -> str:
    """逗号分隔 tag 风格（SD1.5/SDXL，CLIP 编码器）"""
    parts = []
    if style_tag:
        parts.append(style_tag)
    if genre_tag:
        parts.append(genre_tag)
    if scene:
        parts.append(scene)
    if character:
        parts.append(character)
    if action:
        parts.append(action)
    parts.append(emotion_desc)
    parts.append(shot_type)
    parts.append(camera)
    return ", ".join(parts)


def _build_natural_prompt(style_tag: str, genre_tag: str, scene: str, character: str,
                          action: str, emotion: str, emotion_desc: str,
                          shot_type: str, camera: str) -> str:
    """自然语言段落风格（Flux/Cosmos，T5-XXL 编码器）

    将各维度组装为连贯的英文描述段落，充分利用 T5 的自然语言理解能力。
    """
    sentences = []

    # 第一句：整体风格 + 场景
    parts_1 = []
    if style_tag and genre_tag:
        parts_1.append(f"A {style_tag} in {genre_tag}")
    elif style_tag:
        parts_1.append(f"A {style_tag}")
    if scene:
        parts_1.append(f"Set in {scene}")
    if parts_1:
        sentences.append(". ".join(parts_1) + ".")

    # 第二句：角色 + 动作 + 情绪
    # 自然语言模式下跳过中文 action（需先 prepare 翻译，否则中英混杂不自然）
    action_ok = action and all(ord(c) < 127 for c in action)
    parts_2 = []
    if character:
        parts_2.append(character[0].upper() + character[1:] if character else "")
    if action_ok:
        if parts_2:
            parts_2[0] += f" {action}"
        else:
            parts_2.append(action[0].upper() + action[1:] if action else "")
    if emotion and emotion != "neutral":
        if parts_2:
            if action_ok:
                parts_2[0] += f", with a {emotion} expression"
            else:
                parts_2[0] += f" has a {emotion} expression"
        else:
            parts_2.append(f"With a {emotion} expression")
    if parts_2:
        sentences.append(parts_2[0] + ".")

    # 第三句：镜头语言
    camera_parts = []
    camera_parts.append(shot_type)
    if camera and camera != "static camera":
        camera_parts.append(camera)
    sentences.append(", ".join(camera_parts) + ".")

    return " ".join(sentences)


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
