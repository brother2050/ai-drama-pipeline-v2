# 🚀 Trae 导入指南 — 将 LLM 生成的数据导入 AI 短剧管线 v2

> **用途**：将外部 LLM 按 `external-llm-output-spec.md` 规范生成的数据，自动导入到 AI 短剧管线项目中。
>
> **使用方式**：将本文档作为 Trae 的上下文，然后发送导入指令。

---

## 1. 项目目录结构

```
ai-drama-pipeline-v2/
├── projects/
│   └── <项目名>/
│       ├── config/
│       │   ├── project.yaml          ← 项目配置
│       │   ├── characters/
│       │   │   └── <角色id>.yaml     ← 每个角色一个文件
│       │   └── scenes/
│       │       └── <场景id>.yaml     ← 每个场景一个文件
│       ├── storyboard/
│       │   └── episodes.csv          ← 分镜表（所有集）
│       ├── assets/
│       │   ├── characters/<角色id>/  ← 定妆照等
│       │   └── scenes/<场景id>/      ← 场景参考图
│       └── output/                   ← 生成产物
└── docs/
    ├── external-llm-output-spec.md   ← 给三方 LLM 的规范
    └── trae-import-guide.md          ← 本文档
```

---

## 2. 导入任务

当用户提供 LLM 生成的数据（JSON / Markdown / 纯文本）时，按以下步骤执行：

### 2.1 解析输入数据

LLM 输出可能是以下格式之一，需要先提取 JSON：

**格式 A — 纯 JSON**
```json
{ "characters": [...], "scenes": [...], "storyboard": [...] }
```
直接 `JSON.parse()` 即可。

**格式 B — Markdown 中的 JSON 代码块**
````markdown
以下是生成的数据：
```json
{ "characters": [...], ... }
```
````
用正则提取 ````json ... ```` 代码块内容，再 `JSON.parse()`。

**格式 C — 纯文本分段标记**
```
===CHARACTERS===
（JSON 或 YAML 内容）

===SCENES===
（JSON 或 YAML 内容）

===STORYBOARD===
（JSON 或 CSV 内容）
```
按 `===XXX===` 分割各段，分别解析。

**格式 D — 单个 YAML 文件**
```yaml
character:
  id: "linxia"
  ...
```
直接保存为对应的 YAML 文件。

### 2.2 创建/确认项目目录

```bash
# 如果是新项目，创建项目目录
PROJECT="projects/<项目名>"
mkdir -p "$PROJECT/config/characters"
mkdir -p "$PROJECT/config/scenes"
mkdir -p "$PROJECT/storyboard"
mkdir -p "$PROJECT/assets/characters"
mkdir -p "$PROJECT/assets/scenes"
mkdir -p "$PROJECT/output"
mkdir -p "$PROJECT/logs"

# 创建项目配置
cat > "$PROJECT/config/project.yaml" << 'YAML'
project:
  name: "<项目名>"
  episodes: 1
  fps: 24
  style: "cinematic"
  genre: "urban"
YAML
```

### 2.3 导入角色

对 JSON 中 `characters` 数组的每个元素：

**生成 YAML 文件** — 保存到 `config/characters/<id>.yaml`：

```yaml
character:
  id: "<id>"
  name: "<name>"
  gender: "<gender>"
  appearance: "<appearance>"
  appearance_en: "<appearance_en>"
  personality: "<personality>"
  outfits:
    default:
      description: "<outfits.default.description>"
      description_en: "<outfits.default.description_en>"
      reference_images: []
    # ... 其他 outfit
  voice:
    voice_description: "<voice.voice_description>"
    voice_description_en: "<voice.voice_description_en>"
  reference_images: []
```

**字段映射规则**：

| JSON 字段 | YAML 字段 | 必填 | 说明 |
|-----------|-----------|------|------|
| `id` | `character.id` | ✅ | 文件名也用此值 |
| `name` | `character.name` | ✅ | |
| `gender` | `character.gender` | ✅ | |
| `appearance` | `character.appearance` | ✅ | |
| `appearance_en` | `character.appearance_en` | ✅ | 无则用 LLM 翻译 |
| `personality` | `character.personality` | ❌ | 默认空 |
| `outfits` | `character.outfits` | ✅ | 必须含 default |
| `outfits.*.description_en` | `character.outfits.*.description_en` | ✅ | 无则用 LLM 翻译 |
| `voice` | `character.voice` | ✅ | |
| `voice.voice_description_en` | `character.voice.voice_description_en` | ✅ | 无则用 LLM 翻译 |
| — | `character.reference_images` | — | 初始化为 `[]` |

**关键**：`*_en` 英文翻译字段必须存在。如果 LLM 输出中缺失，用以下策略补全：
1. 如果中文描述全是 ASCII（无中文字符），直接复制中文值
2. 否则，用合理的英文翻译填充（可以调用本地 LLM 或手动翻译）

### 2.4 导入场景

对 JSON 中 `scenes` 数组的每个元素：

**生成 YAML 文件** — 保存到 `config/scenes/<id>.yaml`：

```yaml
scene:
  id: "<id>"
  name: "<name>"
  description: "<description>"
  description_en: "<description_en>"
  lighting: "<lighting>"
  lighting_en: "<lighting_en>"
  reference_images: []
```

**字段映射规则**：

| JSON 字段 | YAML 字段 | 必填 |
|-----------|-----------|------|
| `id` | `scene.id` | ✅ |
| `name` | `scene.name` | ✅ |
| `description` | `scene.description` | ✅ |
| `description_en` | `scene.description_en` | ✅ |
| `lighting` | `scene.lighting` | ✅ |
| `lighting_en` | `scene.lighting_en` | ✅ |
| — | `scene.reference_images` | — 初始化为 `[]` |

### 2.5 导入分镜表

将 `storyboard` 数组写入 CSV 文件 `storyboard/episodes.csv`。

**CSV 表头（严格按此顺序）**：
```
episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en,language
```

**写入逻辑**：
```python
import csv

STORYBOARD_FIELDNAMES = [
    "episode", "shot_id", "scene", "characters", "action", "dialogue",
    "camera", "shot_type", "duration", "outfit", "emotion",
    "action_en", "dialogue_en", "language",
]

with open("episodes.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=STORYBOARD_FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(storyboard_data)
```

**注意事项**：
- CSV 中包含逗号的字段（如台词）会被自动加双引号（Python csv 模块默认行为）
- `episode` 和 `duration` 写入为整数
- `language` 缺失时默认填 `zh`
- `shot_id` 必须三位数：`001`, `002`, ...
- `scene` 和 `characters` 中的 ID 必须与 characters/scenes 配置中的 `id` 一致

### 2.6 翻译字段补全策略

如果 LLM 输出中缺少 `*_en` 字段，需要补全：

```
优先级：
1. 如果 LLM 输出已包含 *_en → 直接使用
2. 如果中文值全是 ASCII（无中文字符）→ 复制中文值到 *_en
3. 否则 → 用以下方式翻译：
   a. 调用本地 LLM API（如果可用）
   b. 使用简单规则翻译（适合短文本）
   c. 留空，后续用管线的 "准备阶段" 批量翻译
```

**翻译规则**（如果自行翻译）：
- `appearance_en`：保留数字和专有名词，翻译描述性词汇
- `description_en`：翻译场景描述，保留空间关系词汇
- `action_en`：翻译动作描述，使用动名词形式（sitting, walking...）
- `dialogue_en`：翻译对话，保持口语化

---

## 3. 导入后验证清单

导入完成后，执行以下检查：

```
□ 所有角色 YAML 文件存在于 config/characters/
□ 所有场景 YAML 文件存在于 config/scenes/
□ episodes.csv 文件存在且格式正确
□ 每个角色 YAML 包含 appearance_en 和 voice_description_en
□ 每个场景 YAML 包含 description_en 和 lighting_en
□ 分镜表中的 scene 字段引用的 ID 在场景配置中存在
□ 分镜表中的 characters 字段引用的 ID 在角色配置中存在
□ 所有角色 outfits 中包含 default 键
□ shot_id 从 001 递增，无跳号
□ duration 在 2-8 范围内
```

---

## 4. 激活项目

导入完成后，需要激活新项目才能在 Web 工作台中使用：

```bash
# 写入 .active 文件指向新项目
echo "$(pwd)/projects/<项目名>" > projects/.active
```

---

## 5. 完整导入脚本参考

以下是一个完整的 Python 导入脚本，Trae 可以参考其逻辑：

```python
#!/usr/bin/env python3
"""外部 LLM 数据导入脚本"""
import json, csv, os, re
from pathlib import Path

# ── 配置 ──
ROOT = Path(__file__).resolve().parent
PROJECT_NAME = "my_project"  # ← 修改为你的项目名
INPUT_FILE = "llm_output.json"  # ← LLM 输出的文件路径

# ── 读取输入 ──
def load_input(path: str) -> dict:
    """支持 JSON / Markdown JSON 代码块 / 纯文本分段"""
    text = Path(path).read_text(encoding="utf-8")

    # 尝试直接解析 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试从 Markdown 代码块提取
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试分段解析
    result = {}
    for key in ("characters", "scenes", "storyboard"):
        pattern = rf"==={key.upper()}===\s*\n(.*?)(?====|\Z)"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            content = m.group(1).strip()
            try:
                result[key] = json.loads(content)
            except json.JSONDecodeError:
                # 尝试 YAML
                try:
                    import yaml
                    result[key] = yaml.safe_load(content)
                except Exception:
                    pass

    if not result:
        raise ValueError(f"无法解析输入文件: {path}")
    return result


# ── 翻译补全 ──
def ensure_en(value: str, en_value: str) -> str:
    """确保英文翻译字段存在"""
    if en_value:
        return en_value
    if not value:
        return ""
    # 如果全是 ASCII，直接复制
    if all(ord(c) < 128 for c in value):
        return value
    # 否则返回空，后续用管线翻译
    return ""


# ── 导入角色 ──
def import_characters(chars: list, project_dir: Path):
    char_dir = project_dir / "config" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)

    for c in chars:
        cid = c.get("id", "")
        if not cid:
            continue

        # 构建 outfits（补全 description_en）
        outfits = {}
        for key, val in (c.get("outfits") or {}).items():
            if isinstance(val, dict):
                outfits[key] = {
                    "description": val.get("description", ""),
                    "description_en": ensure_en(val.get("description", ""), val.get("description_en", "")),
                    "reference_images": val.get("reference_images", []),
                }
        if "default" not in outfits:
            outfits["default"] = {"description": "", "description_en": "", "reference_images": []}

        # 构建 voice（补全 voice_description_en）
        voice = c.get("voice") or {}
        voice_data = {
            "voice_description": voice.get("voice_description", ""),
            "voice_description_en": ensure_en(
                voice.get("voice_description", ""),
                voice.get("voice_description_en", "")
            ),
        }

        # 写入 YAML
        import yaml
        data = {
            "character": {
                "id": cid,
                "name": c.get("name", cid),
                "gender": c.get("gender", ""),
                "appearance": c.get("appearance", ""),
                "appearance_en": ensure_en(c.get("appearance", ""), c.get("appearance_en", "")),
                "personality": c.get("personality", ""),
                "outfits": outfits,
                "voice": voice_data,
                "reference_images": [],
            }
        }
        path = char_dir / f"{cid}.yaml"
        path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
        print(f"  ✅ 角色: {c.get('name', cid)} → {path.name}")


# ── 导入场景 ──
def import_scenes(scenes: list, project_dir: Path):
    scene_dir = project_dir / "config" / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)

    for s in scenes:
        sid = s.get("id", "")
        if not sid:
            continue

        import yaml
        data = {
            "scene": {
                "id": sid,
                "name": s.get("name", sid),
                "description": s.get("description", ""),
                "description_en": ensure_en(s.get("description", ""), s.get("description_en", "")),
                "lighting": s.get("lighting", ""),
                "lighting_en": ensure_en(s.get("lighting", ""), s.get("lighting_en", "")),
                "reference_images": [],
            }
        }
        path = scene_dir / f"{sid}.yaml"
        path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
        print(f"  ✅ 场景: {s.get('name', sid)} → {path.name}")


# ── 导入分镜 ──
def import_storyboard(storyboard: list, project_dir: Path):
    sb_dir = project_dir / "storyboard"
    sb_dir.mkdir(parents=True, exist_ok=True)

    FIELDNAMES = [
        "episode", "shot_id", "scene", "characters", "action", "dialogue",
        "camera", "shot_type", "duration", "outfit", "emotion",
        "action_en", "dialogue_en", "language",
    ]

    path = sb_dir / "episodes.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for shot in storyboard:
            # 确保必要字段
            shot.setdefault("language", "zh")
            shot.setdefault("outfit", "default")
            shot.setdefault("emotion", "neutral")
            shot.setdefault("action_en", ensure_en(shot.get("action", ""), shot.get("action_en", "")))
            shot.setdefault("dialogue_en", ensure_en(shot.get("dialogue", ""), shot.get("dialogue_en", "")))
            writer.writerow(shot)

    print(f"  ✅ 分镜: {len(storyboard)} 个镜头 → {path.name}")


# ── 主流程 ──
def main():
    print(f"📂 项目: {PROJECT_NAME}")
    project_dir = ROOT / "projects" / PROJECT_NAME

    # 创建目录
    for d in ["config/characters", "config/scenes", "storyboard",
              "assets/characters", "assets/scenes", "output", "logs"]:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # 创建项目配置
    cfg_path = project_dir / "config" / "project.yaml"
    if not cfg_path.exists():
        import yaml
        cfg = {"project": {"name": PROJECT_NAME, "episodes": 1, "fps": 24, "style": "cinematic", "genre": "urban"}}
        cfg_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # 读取输入
    data = load_input(str(ROOT / INPUT_FILE))

    # 导入
    if "characters" in data:
        print(f"\n👤 导入角色 ({len(data['characters'])} 个)...")
        import_characters(data["characters"], project_dir)

    if "scenes" in data:
        print(f"\n🏔 导入场景 ({len(data['scenes'])} 个)...")
        import_scenes(data["scenes"], project_dir)

    if "storyboard" in data:
        print(f"\n📝 导入分镜 ({len(data['storyboard'])} 个镜头)...")
        import_storyboard(data["storyboard"], project_dir)

    # 激活项目
    active_file = ROOT / "projects" / ".active"
    active_file.write_text(str(project_dir.resolve()), encoding="utf-8")
    print(f"\n✅ 项目已激活: {project_dir}")

    # 验证
    print("\n🔍 验证...")
    errors = []
    chars_ids = {c["id"] for c in data.get("characters", []) if c.get("id")}
    scenes_ids = {s["id"] for s in data.get("scenes", []) if s.get("id")}

    for shot in data.get("storyboard", []):
        sid = shot.get("scene", "")
        if sid and sid not in scenes_ids:
            errors.append(f"镜头 {shot.get('shot_id')} 引用了不存在的场景: {sid}")
        for cid in shot.get("characters", "").split("+"):
            cid = cid.strip()
            if cid and cid not in chars_ids:
                errors.append(f"镜头 {shot.get('shot_id')} 引用了不存在的角色: {cid}")

    if errors:
        print("  ⚠ 警告:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  ✅ 全部通过")

    print("\n🎬 导入完成！启动 Web 工作台查看：drama serve")


if __name__ == "__main__":
    main()
```

---

## 6. Trae 使用示例

### 场景：用户给了一个 JSON 文件，需要导入

**用户消息**：
> 我有一个 LLM 生成的短剧数据文件 `output.json`，请帮我导入到项目 `love_story` 中。

**Trae 执行**：
1. 读取 `output.json`
2. 解析 JSON
3. 创建 `projects/love_story/` 目录结构
4. 为每个角色生成 `config/characters/<id>.yaml`
5. 为每个场景生成 `config/scenes/<id>.yaml`
6. 生成 `storyboard/episodes.csv`
7. 补全缺失的 `*_en` 字段
8. 写入 `projects/.active` 激活项目
9. 运行验证检查
10. 输出导入报告
