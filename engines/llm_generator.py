"""LLM 内容生成引擎 — 从大纲生成分镜、角色、场景"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

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
    "dialogue": "中文台词，无台词用 ......",
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
- 注意镜头语言的节奏感：特写→中景→全景交替，避免连续相同景别
- 情绪要有起伏，不要全程 neutral
- 【重要】action 和 dialogue 中描述角色时，必须使用中文名（参考"角色名映射"），严禁中英文混搭（如"林xia"是错误的，应为"林夏"）
- 如果角色没有中文名，自行起一个合理的中文名并在整个分镜中保持一致
- 只输出 JSON，不要任何额外文字"""


def generate_storyboard(llm, outline: str, characters: list[dict] = None,
                        scenes: list[dict] = None, episode: int = 1,
                        target_duration: int = 90) -> list[dict]:
    """从剧情大纲生成分镜表

    Args:
        llm: LLM 后端实例（需有 chat 方法）
        outline: 剧情大纲文本
        characters: 已有角色列表 [{id, name, appearance, ...}]
        scenes: 已有场景列表 [{id, name, description, ...}]
        episode: 集数
        target_duration: 目标总时长（秒）

    Returns:
        镜头列表 [{shot_id, scene, characters, action, dialogue, ...}]
    """
    # 构建上下文
    context_parts = [f"=== 第{episode}集 剧情大纲 ===\n{outline}"]

    if characters:
        # 角色名映射 — LLM 在 action/dialogue 中必须用中文名，characters 字段用英文 ID
        char_map_lines = []
        char_info_lines = []
        for c in characters:
            cid = c.get("id", "?")
            cname = c.get("name", cid)
            char_map_lines.append(f"  {cid} → {cname}")
            char_info_lines.append(f"- {cid}（{cname}）: {c.get('appearance', '')[:60]}")
        context_parts.append(f"\n=== 角色名映射（characters 字段写英文 ID，action/dialogue 中写中文名） ===\n" + "\n".join(char_map_lines))
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

    try:
        raw = llm.chat(prompt, system=STORYBOARD_SYSTEM, max_tokens=4096)
        shots = _parse_json_response(raw)
        if not shots:
            logger.error("LLM 返回无法解析为镜头列表")
            return []

        # 后处理
        shots = _postprocess_shots(shots, episode)
        logger.info(f"生成 {len(shots)} 个镜头, 预计 {sum(int(s.get('duration', 4)) for s in shots)} 秒")
        return shots

    except Exception as e:
        logger.error(f"LLM 分镜生成失败: {e}")
        return []


# ── 角色生成 ──

CHARACTER_SYSTEM = """你是一位专业的短剧角色设计师。根据用户提供的角色描述，生成完整的角色配置。

输出格式要求（严格 JSON 对象）：
```json
{
  "id": "英文小写下划线ID",
  "name": "中文名",
  "gender": "male/female",
  "appearance": "详细外貌描述（50-100字），包含年龄、发型、五官、体型、身高等",
  "outfits": {
    "标签名": "该套服装的详细描述（30-50字）"
  },
  "voice": {
    "voice_description": "声音特征描述（20-40字），包含音色、语速、口音等"
  },
  "personality": "性格特征简述（20-40字）"
}
```

规则：
- id 必须是英文小写+下划线，简短有意义
- appearance 要足够详细，能指导 AI 绘图
- 至少准备 2 套服装（如 casual、formal、home 等）
- voice_description 要有辨识度
- 只输出 JSON，不要额外文字"""


def generate_characters(llm, descriptions: list[str], expected_ids: list[str] | None = None) -> list[dict]:
    """从描述生成角色配置

    Args:
        llm: LLM 后端实例
        descriptions: 角色描述列表，每项是一段自然语言描述
        expected_ids: 与 descriptions 一一对应的预期 ID 列表，生成后强制使用

    Returns:
        角色配置列表
    """
    results = []
    for i, desc in enumerate(descriptions):
        if not desc.strip():
            continue
        logger.info(f"LLM 生成角色: {desc[:40]}...")
        try:
            raw = llm.chat(desc, system=CHARACTER_SYSTEM, max_tokens=1024)
            char = _parse_json_response(raw)
            if char and isinstance(char, dict):
                if expected_ids and i < len(expected_ids):
                    char["id"] = expected_ids[i]
                results.append(char)
                logger.info(f"  ✅ 生成角色: {char.get('name', '?')} ({char.get('id', '?')})")
            else:
                logger.warning(f"  ⚠ 解析失败")
        except Exception as e:
            logger.error(f"  ❌ 角色生成失败: {e}")
    return results


# ── 场景生成 ──

SCENE_SYSTEM = """你是一位专业的短剧场景设计师。根据用户提供的场景描述，生成完整的场景配置。

输出格式要求（严格 JSON 对象）：
```json
{
  "id": "英文小写下划线ID",
  "name": "场景中文名",
  "description": "详细场景描述（50-100字），包含空间布局、家具摆设、色调、氛围等，能指导 AI 绘图",
  "lighting": "光照描述（20-40字），包含光源方向、色温、明暗对比等"
}
```

规则：
- id 必须是英文小写+下划线
- description 要有画面感，能直接用于生成图片
- lighting 要具体到色温和方向
- 只输出 JSON，不要额外文字"""


def generate_scenes(llm, descriptions: list[str], expected_ids: list[str] | None = None) -> list[dict]:
    """从描述生成场景配置

    Args:
        llm: LLM 后端实例
        descriptions: 场景描述列表
        expected_ids: 与 descriptions 一一对应的预期 ID 列表，生成后强制使用

    Returns:
        场景配置列表
    """
    results = []
    for i, desc in enumerate(descriptions):
        if not desc.strip():
            continue
        logger.info(f"LLM 生成场景: {desc[:40]}...")
        try:
            raw = llm.chat(desc, system=SCENE_SYSTEM, max_tokens=1024)
            scene = _parse_json_response(raw)
            if scene and isinstance(scene, dict):
                if expected_ids and i < len(expected_ids):
                    scene["id"] = expected_ids[i]
                results.append(scene)
                logger.info(f"  ✅ 生成场景: {scene.get('name', '?')} ({scene.get('id', '?')})")
            else:
                logger.warning(f"  ⚠ 解析失败")
        except Exception as e:
            logger.error(f"  ❌ 场景生成失败: {e}")
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
        logger.error(f"大纲扩写失败: {e}")
        return outline


# ── 内部工具 ──

def _parse_json_response(text: str) -> Any:
    """从 LLM 回复中提取 JSON（兼容 markdown 代码块、单引号、注释等）"""
    if not text:
        return None

    text = text.strip()

    # 1. 去掉 markdown 代码块
    patterns = [
        r'```json\s*\n?(.*?)\n?\s*```',
        r'```\s*\n?(.*?)\n?\s*```',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            text = m.group(1).strip()
            break

    # 2. 直接尝试
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. 去掉尾随逗号
    fixed = re.sub(r',\s*([\]}])', r'\1', text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4. 去掉行注释 (// ...)
    fixed = re.sub(r'//[^\n]*', '', fixed)
    fixed = re.sub(r',\s*([\]}])', r'\1', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. 单引号 → 双引号（Python 风格 dict → JSON）
    if "'" in text and '"' not in text:
        fixed = text.replace("'", '"')
        fixed = re.sub(r',\s*([\]}])', r'\1', fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    # 6. 从大段文本中提取最外层 JSON（找匹配的 [] 或 {}）
    for start_ch, end_ch in [('[', ']'), ('{', '}')]:
        idx = text.find(start_ch)
        if idx < 0:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(idx, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_str:
                escape = True
                continue
            if c == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == start_ch:
                depth += 1
            elif c == end_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[idx:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # 尝试修复后解析
                        candidate = re.sub(r',\s*([\]}])', r'\1', candidate)
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break

    # 7. 最后尝试：去掉所有换行和多余空白后解析
    oneline = re.sub(r'\s+', ' ', text).strip()
    if oneline.startswith('[') or oneline.startswith('{'):
        try:
            return json.loads(oneline)
        except json.JSONDecodeError:
            pass

    logger.warning(f"无法从 LLM 回复中提取 JSON（前 200 字）: {text[:200]}")
    return None


def _postprocess_shots(shots: list[dict], episode: int) -> list[dict]:
    """后处理镜头列表"""
    result = []
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        # 确保 shot_id
        if not shot.get("shot_id"):
            shot["shot_id"] = f"{i+1:03d}"
        # 确保 episode
        shot["episode"] = episode
        # 限制 duration 范围
        try:
            d = int(shot.get("duration", 4))
            shot["duration"] = max(2, min(8, d))
        except (ValueError, TypeError):
            shot["duration"] = 4
        # 清理 dialogue 中的引号
        if shot.get("dialogue"):
            shot["dialogue"] = shot["dialogue"].strip('"\'')
        result.append(shot)
    return result
