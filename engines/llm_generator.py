"""LLM 内容生成引擎 — 从大纲生成分镜、角色、场景"""
from __future__ import annotations

import logging
import re

from infra.json_parse import parse_llm_json

logger = logging.getLogger(__name__)

__all__ = [
    "generate_storyboard",
    "generate_characters",
    "generate_scenes",
    "expand_outline",
]


# ── 分镜表生成 ──

STORYBOARD_SYSTEM = """你是一位专业的短剧分镜师。根据用户提供的剧情大纲，将其拆分为具体的镜头列表。

输出格式要求（严格 JSON 数组）：
```json
[
  {
    "shot_id": "001",
    "scene": "场景ID（英文小写下划线，如 living_room, street, cafe）",
    "characters": "角色ID（英文小写下划线，多人用+连接，如 linxia+guchen）",
    "action": "中文动作描述，具体到肢体语言",
    "action_en": "英文动作描述（与 action 对应，用于英文字幕）",
    "dialogue": "中文台词，无台词用 ......",
    "dialogue_en": "英文台词（与 dialogue 对应，用于英文字幕），无台词用 ......",
    "camera": "运镜：固定/缓慢推近/跟随平移/手持晃动/环绕/俯视/仰视",
    "shot_type": "景别：特写/近景/中景/过肩/全身/全景/远景/双人全景",
    "duration": "秒数（2-8之间的整数）",
    "emotion": "情绪：happy/sad/worried/surprised/angry/romantic/calm/determined/serious/neutral",
    "outfit": "服装标签（对应角色配置中的 outfits key）"
  }
]
```

规则：
- shot_id 三位数，从 001 递增
- 每个镜头 2-8 秒，总时长尽量控制在 60-120 秒
- 场景和角色使用英文 ID，动作和台词用中文
- dialogue 不要包含引号，省略号用 ...
- action_en 和 dialogue_en 是对应中文内容的英文翻译，用于英文字幕，必须填写
- 注意镜头语言的节奏感：特写→中景→全景交替，避免连续相同景别
- 情绪要有起伏，不要全程 neutral
- 【重要】action 和 dialogue 中描述角色时，使用该角色的真实名字（参考"角色名映射"），保持一致，严禁中英文混搭（如"林xia"是错误的，应为"林夏"；同样"Joh翰"也是错误的，应为"John"）
- 只输出 JSON，不要任何额外文字"""


def generate_storyboard(llm, outline: str, characters: list[dict] = None,
                        scenes: list[dict] = None, episode: int = 1,
                        target_duration: int = 90,
                        style: str = "", genre: str = "") -> list[dict]:
    """从剧情大纲生成分镜表

    Args:
        llm: LLM 后端实例（需有 chat 方法）
        outline: 剧情大纲文本
        characters: 已有角色列表 [{id, name, appearance, ...}]
        scenes: 已有场景列表 [{id, name, description, ...}]
        episode: 集数
        target_duration: 目标总时长（秒）
        style: 视觉风格（如 cinematic, anime, realistic）
        genre: 题材类型（如 urban, romance, suspense）

    Returns:
        镜头列表 [{shot_id, scene, characters, action, dialogue, ...}]
    """
    # 构建上下文
    context_parts = [f"=== 第{episode}集 剧情大纲 ===\n{outline}"]

    if style or genre:
        style_info = []
        if style:
            style_info.append(f"视觉风格: {style}")
        if genre:
            style_info.append(f"题材类型: {genre}")
        context_parts.append(f"\n=== 创作方向 ===\n" + "，".join(style_info))

    if characters:
        # 角色名映射 — LLM 在 action/dialogue 中必须用角色真实名字，characters 字段用英文 ID
        char_map_lines = []
        char_info_lines = []
        for c in characters:
            cid = c.get("id", "?")
            cname = c.get("name", cid)
            char_map_lines.append(f"  {cid} → {cname}")
            char_info_lines.append(f"- {cid}（{cname}，性格：{c.get('personality', '未指定')}）: {c.get('appearance', '')[:60]}")
        context_parts.append(f"\n=== 角色名映射（characters 字段写英文 ID，action/dialogue 中写角色真实名字） ===\n" + "\n".join(char_map_lines))
        context_parts.append(f"\n=== 已有角色详情 ===\n" + "\n".join(char_info_lines))

    if scenes:
        scene_info = "\n".join(
            f"- {s.get('id', '?')}（{s.get('name', '?')}）: {s.get('description', '')[:60]}"
            for s in scenes
        )
        context_parts.append(f"\n=== 已有场景 ===\n{scene_info}")

    context_parts.append(f"\n目标总时长约 {target_duration} 秒，每个镜头 2-8 秒。")

    prompt = "\n".join(context_parts)

    logger.info(f"LLM 生成分镜: 大纲 {len(outline)} 字, 目标 {target_duration}s")

    import time as _time
    shots = None
    for attempt in range(3):
        try:
            raw = llm.chat(prompt, system=STORYBOARD_SYSTEM, max_tokens=4096)
            shots = parse_llm_json(raw)
            if shots:
                break
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(f"  ⚠ 分镜 JSON 解析失败（尝试 {attempt+1}/3），{wait}s 后重试")
                _time.sleep(wait)
        except Exception as e:
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(f"  ⚠ 分镜生成失败（尝试 {attempt+1}/3）: {e}，{wait}s 后重试")
                _time.sleep(wait)
            else:
                logger.error(f"  ❌ 分镜生成最终失败: {e}", exc_info=True)

    if not shots:
        logger.error("LLM 返回无法解析为镜头列表")
        return []

    # 后处理
    shots = _postprocess_shots(shots, episode)
    logger.info(f"生成 {len(shots)} 个镜头, 预计 {sum(int(s.get('duration', 4)) for s in shots)} 秒")
    return shots


# ── 角色生成 ──

CHARACTER_SYSTEM = """你是一位专业的短剧角色设计师。根据用户提供的角色描述，生成完整的角色配置。

输出格式要求（严格 JSON 对象）：
```json
{
  "id": "由调用方指定的角色ID，原样填入，如 ghost01、lifei 等",
  "name": "该角色的真实名字（根据角色背景可以是中文、英文或其他语言，必须与 id 对应，不能与其他角色重名）",
  "gender": "male/female",
  "appearance": "详细外貌描述（50-100字），包含年龄、发型、五官、体型、身高等",
  "personality": "性格特征简述（20-40字）",
  "outfits": {
    "default": {"description": "默认服装的详细描述（30-50字）", "reference_images": []},
    "casual": {"description": "休闲装描述（30-50字）", "reference_images": []},
    "formal": {"description": "正装描述（30-50字）", "reference_images": []}
  },
  "voice": {
    "voice_description": "声音特征描述（20-40字），包含音色、语速、口音等"
  }
}
```

规则：
- id 字段必须原样填入调用方提供的值，不可自行生成或修改
- name 必须是该角色独有的真实名字，根据角色背景可以是中文、英文或其他语言，绝不能与其他角色重名；从描述中推断角色身份并取一个合适的名字
- personality 必须填写，从描述中推断角色性格（如"外冷内热"、"善良胆小"、"沉稳理性"等），20-40字
- appearance 要足够详细，能指导 AI 绘图
- outfits 必须包含 "default" 键作为默认服装，可额外添加 casual、formal、home 等
- outfits 中每个服装的 reference_images 必须为空数组 []，禁止填入任何 URL（图片由系统自动生成）
- voice.voice_description 声音描述要有辨识度
- 只输出 JSON，不要额外文字"""


def _normalize_character(char: dict) -> dict:
    """规范化角色数据，确保 voice / outfits / personality 格式符合前端预期"""
    # personality: 确保有值
    if not char.get("personality"):
        char["personality"] = ""

    # voice: 确保有 voice_description 字段
    voice = char.get("voice")
    if isinstance(voice, dict):
        voice.setdefault("voice_description", "")
        char["voice"] = voice
    elif voice is None:
        char["voice"] = {"voice_description": ""}

    # reference_images: 由系统管理（定妆照/上传），LLM 不应填充外部 URL
    refs = char.get("reference_images")
    if isinstance(refs, list) and any(isinstance(r, str) and r.startswith("http") for r in refs):
        logger.debug("清理 character.reference_images 中的外部 URL")
        char["reference_images"] = []

    # outfits: 确保有 default 键，值统一为 dict 格式
    outfits = char.get("outfits")
    if isinstance(outfits, dict):
        if "default" not in outfits:
            first_val = next(iter(outfits.values()), "")
            outfits["default"] = first_val
        # 统一转为 dict 格式
        for k, v in outfits.items():
            if isinstance(v, str):
                outfits[k] = {"description": v, "reference_images": []}
            elif isinstance(v, dict):
                v.setdefault("description", "")
                v.setdefault("reference_images", [])
                # 清理 LLM 注入的外部 URL（reference_images 由系统管理，LLM 不应填充）
                refs = v.get("reference_images", [])
                if refs and any(isinstance(r, str) and r.startswith("http") for r in refs):
                    logger.debug(f"清理 outfits.{k}.reference_images 中的外部 URL")
                    v["reference_images"] = []
        char["outfits"] = outfits
    elif outfits is None:
        char["outfits"] = {"default": {"description": "", "reference_images": []}}

    return char


def generate_characters(llm, descriptions: list[str], expected_ids: list[str] | None = None) -> list[dict]:
    """从描述生成角色配置 — 全部成功或抛异常

    Args:
        llm: LLM 后端实例
        descriptions: 角色描述列表
        expected_ids: 与 descriptions 一一对应的预期 ID 列表

    Returns:
        角色配置列表，与 descriptions 等长

    Raises:
        RuntimeError: 有任何角色生成最终失败时
    """
    import time as _time

    results = []
    used_names: set[str] = set()
    failed_indices: list[int] = []

    for i, desc in enumerate(descriptions):
        if not desc.strip():
            results.append(None)
            continue
        logger.info(f"LLM 生成角色: {desc[:40]}...")

        char = None
        for attempt in range(3):
            try:
                raw = llm.chat(desc, system=CHARACTER_SYSTEM, max_tokens=1024)
                char = parse_llm_json(raw)
                if char and isinstance(char, dict):
                    break
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"  ⚠ 角色 {i+1} JSON 解析失败（尝试 {attempt+1}/3），{wait}s 后重试")
                    _time.sleep(wait)
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"  ⚠ 角色 {i+1} 生成失败（尝试 {attempt+1}/3）: {e}，{wait}s 后重试")
                    _time.sleep(wait)
                else:
                    logger.error(f"  ❌ 角色 {i+1} 生成最终失败: {e}", exc_info=True)

        if char and isinstance(char, dict):
            if expected_ids and i < len(expected_ids):
                char["id"] = expected_ids[i]
            char = _normalize_character(char)
            cname = char.get("name", "").strip()
            if cname in used_names:
                counter = 2
                while f"{cname}{counter}" in used_names:
                    counter += 1
                new_name = f"{cname}{counter}"
                logger.warning(f"  ⚠ 角色名重复: {cname} → {new_name}")
                char["name"] = new_name
                cname = new_name
            used_names.add(cname)
            results.append(char)
            logger.info(f"  ✅ 生成角色: {char.get('name', '?')} ({char.get('id', '?')})")
        else:
            results.append(None)
            failed_indices.append(i)
            logger.error(f"  ❌ 角色 {i+1} 生成失败")

    if failed_indices:
        failed_ids = [descriptions[i][:20] for i in failed_indices]
        raise RuntimeError(
            f"角色生成失败（{len(failed_indices)}/{len(descriptions)} 个）: "
            f"{', '.join(failed_ids)}... 请检查 LLM 服务后重试。"
        )

    return results


# ── 场景生成 ──

SCENE_SYSTEM = """你是一位专业的短剧场景设计师。根据用户提供的场景描述，生成完整的场景配置。

输出格式要求（严格 JSON 对象）：
```json
{
  "id": "场景ID（由调用方指定，原样填入，不可修改）",
  "name": "场景名",
  "description": "详细场景描述（50-100字），包含空间布局、家具摆设、色调、氛围等，能指导 AI 绘图",
  "lighting": "光照描述（20-40字），包含光源方向、色温、明暗对比等"
}
```

规则：
- id 字段必须原样填入调用方提供的值，不可自行生成或修改
- description 要有画面感，能直接用于生成图片
- lighting 要具体到色温和方向
- 只输出 JSON，不要额外文字"""


def generate_scenes(llm, descriptions: list[str], expected_ids: list[str] | None = None) -> list[dict]:
    """从描述生成场景配置 — 全部成功或抛异常

    Args:
        llm: LLM 后端实例
        descriptions: 场景描述列表
        expected_ids: 与 descriptions 一一对应的预期 ID 列表

    Returns:
        场景配置列表，与 descriptions 等长

    Raises:
        RuntimeError: 有任何场景生成最终失败时
    """
    import time as _time

    results = []
    used_names: set[str] = set()
    failed_indices: list[int] = []

    for i, desc in enumerate(descriptions):
        if not desc.strip():
            results.append(None)
            continue
        logger.info(f"LLM 生成场景: {desc[:40]}...")

        scene = None
        for attempt in range(3):
            try:
                raw = llm.chat(desc, system=SCENE_SYSTEM, max_tokens=1024)
                scene = parse_llm_json(raw)
                if scene and isinstance(scene, dict):
                    break
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"  ⚠ 场景 {i+1} JSON 解析失败（尝试 {attempt+1}/3），{wait}s 后重试")
                    _time.sleep(wait)
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    logger.warning(f"  ⚠ 场景 {i+1} 生成失败（尝试 {attempt+1}/3）: {e}，{wait}s 后重试")
                    _time.sleep(wait)
                else:
                    logger.error(f"  ❌ 场景 {i+1} 生成最终失败: {e}", exc_info=True)

        if scene and isinstance(scene, dict):
            if expected_ids and i < len(expected_ids):
                scene["id"] = expected_ids[i]
            sname = scene.get("name", "").strip()
            if sname in used_names:
                counter = 2
                while f"{sname}{counter}" in used_names:
                    counter += 1
                new_name = f"{sname}{counter}"
                logger.warning(f"  ⚠ 场景名重复: {sname} → {new_name}")
                scene["name"] = new_name
                sname = new_name
            used_names.add(sname)
            results.append(scene)
            logger.info(f"  ✅ 生成场景: {scene.get('name', '?')} ({scene.get('id', '?')})")
        else:
            results.append(None)
            failed_indices.append(i)
            logger.error(f"  ❌ 场景 {i+1} 生成失败")

    if failed_indices:
        failed_ids = [descriptions[i][:20] for i in failed_indices]
        raise RuntimeError(
            f"场景生成失败（{len(failed_indices)}/{len(descriptions)} 个）: "
            f"{', '.join(failed_ids)}... 请检查 LLM 服务后重试。"
        )

    return results


# ── 大纲扩写 ──

EXPAND_SYSTEM = """你是一位短剧编剧。根据用户提供的简短大纲，扩写为更详细的分镜大纲。

要求：
1. 补充角色的心理活动和微表情
2. 增加环境细节和氛围描写
3. 设计有节奏感的对话（起承转合）
4. 标注关键情绪转折点
5. 保持原有剧情走向不变

直接输出扩写后的中文大纲，不要加标题或格式。"""


def expand_outline(llm, outline: str) -> str:
    """扩写简短大纲为详细版本"""
    if not outline.strip():
        return outline
    try:
        return llm.chat(outline, system=EXPAND_SYSTEM, max_tokens=2048)
    except Exception as e:
        logger.error(f"大纲扩写失败: {e}", exc_info=True)
        return outline


# ── 内部工具 ──


def _postprocess_shots(shots: list[dict], episode: int) -> list[dict]:
    """后处理镜头列表"""
    result = []
    used_ids: set[str] = set()
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        # 确保 shot_id（去重：LLM 可能返回重复 ID）
        sid = shot.get("shot_id", "")
        if not sid:
            sid = f"{i+1:03d}"
        # 校验 shot_id 格式：三位数数字，不符合则重新编号
        if not re.match(r"^\d{3}$", sid) or sid in used_ids:
            old_sid = sid
            sid = f"{i+1:03d}"
            if old_sid != sid:
                logger.warning(f"镜头 shot_id '{old_sid}' 格式无效或重复，自动重编号为 {sid}")
        shot["shot_id"] = sid
        used_ids.add(sid)
        # 确保 episode（统一为字符串，与 CSV 读取行为一致）
        shot["episode"] = str(episode)
        # 限制 duration 范围（截断时警告，避免用户不知情），统一为 int
        try:
            d = int(shot.get("duration", 4))
            clamped = max(2, min(8, d))
            if clamped != d:
                logger.warning(f"镜头 {sid} duration={d} 超出范围 [2,8]，已截断为 {clamped}")
            shot["duration"] = clamped
        except (ValueError, TypeError):
            logger.warning(f"镜头 {sid} duration 格式无效，使用默认值 4")
            shot["duration"] = 4
        # 清理 dialogue / action_en / dialogue_en 中的多余引号
        # 只去除首尾成对的引号，保留内容中有意义的引号
        for _k in ("dialogue", "action_en", "dialogue_en"):
            val = shot.get(_k, "")
            if val:
                # 去除首尾成对引号: "..." → ... / '...' → ...
                if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
                    val = val[1:-1]
                elif len(val) >= 2 and val[0] == "'" and val[-1] == "'":
                    val = val[1:-1]
                shot[_k] = val
        # 校验 emotion 合法值（不在 EMOTION_MAP 中的回退到 neutral）
        emotion = shot.get("emotion", "neutral")
        valid_emotions = {"angry", "sad", "happy", "worried", "surprised", "smug",
                          "serious", "calm", "determined", "fearful", "neutral", "romantic", "action"}
        if emotion not in valid_emotions:
            logger.warning(f"镜头 {sid} emotion='{emotion}' 不在合法值列表中，回退到 neutral")
            shot["emotion"] = "neutral"
        result.append(shot)
    return result
