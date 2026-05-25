"""项目管理 — 纯 Python

所有项目（含默认）统一存放在 projects/ 下。
每个项目完全独立：自己的角色、场景、剧本、配置。
"""
from __future__ import annotations

import csv
import logging
import shutil
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "default"

# 每个项目必须具备的目录结构
_PROJECT_DIRS = [
    "config",
    "config/characters",
    "config/scenes",
    "storyboard",
    "assets/characters",
    "assets/scenes",
    "assets/loras",
    "output",
    "logs",
]

# 默认项目配置模板
_DEFAULT_PROJECT_YAML = """\
# AI 短剧管线 v2 — 项目配置

project:
  name: "{name}"
  episodes: 1
  fps: 24
  resolution: [1280, 720]
  style: "cinematic"
  genre: "urban"

# ComfyUI 服务器地址
comfyui:
  url: "http://127.0.0.1:8188"
  timeout: 300
  api_key: ""

# 模型后端选择
models:
  image_backend: "sd15"
  video_backend: "animatediff"
  tts_backend: "mimo-voicedesign"
  lip_sync_backend: "musetalk"
  music_backend: "template"

  # TTS 服务地址
  gpt_sovits:
    api_url: "http://127.0.0.1:9880"

  # 口型同步服务地址
  musetalk:
    api_url: "http://127.0.0.1:8080"
  sadtalker:
    api_url: "http://127.0.0.1:8082"
  wav2lip:
    api_url: "http://127.0.0.1:8084"

# LLM 配置（可选）
llm:
  enabled: false
  backend: "ollama"
  base_url: "http://localhost:11434"
  model: "qwen3:8b"

# LoRA 训练（FluxGym 远程训练）
training:
  enabled: false
  backend: "fluxgym"
  api_url: "http://127.0.0.1:7860"
  poll_interval: 10
  defaults:
    steps: 1000
    learning_rate: 0.0001
    rank: 16
    resolution: "512x768"

# Web 服务器
server:
  port: 8888
  host: "0.0.0.0"
  cors_origin: "*"

# 后期合成
post_production:
  transition: "crossfade"
  transition_duration: 0.5
  bgm_volume: 0.15
  subtitle_platform: "douyin"

# 超时配置
timeouts:
  comfyui: 300
  tts: 60
  lipsync: 120
  llm: 300
  music: 120
"""

# 默认分镜表模板（空表头）
_DEFAULT_STORYBOARD_CSV = """\
episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en
"""

# 示例角色模板
_EXAMPLE_CHARACTER = """\
# 角色配置 — 复制此文件并改名（如 zhangsan.yaml），填入角色信息

character:
  id: "{char_id}"
  name: "{name}"
  gender: "{gender}"
  appearance: >-
    （填写外貌特征，越详细越好，用于 AI 生成定妆照和一致性保持）
    例如：22岁年轻女性，长发，瓜子脸，大眼睛，身高165cm，体型偏瘦
  outfits:
    casual: >-
      （填写日常服装描述）
    formal: >-
      （填写正式场合服装描述，可选）
  voice:
    voice_description: "（填写声音特征描述，用于 TTS 语音合成）"
"""

# 示例场景模板
_EXAMPLE_SCENE = """\
# 场景配置 — 复制此文件并改名（如 office.yaml），填入场景信息

scene:
  id: "{scene_id}"
  name: "{name}"
  description: >-
    （填写场景的详细描述，包括空间布局、主要物件、色调氛围等）
    例如：现代简约风格客厅，米色沙发，落地窗，暖色调灯光
  lighting: "（填写光照描述）例如：暖色室内光，自然光从窗户照入"
"""


def _active(root: Path) -> Path:
    """返回当前活动项目路径。无 .active 时回退到 projects/default/"""
    f = root / "projects" / ".active"
    if f.exists():
        p = Path(f.read_text().strip())
        if p.exists():
            return p
    return root / "projects" / DEFAULT_PROJECT


def _ensure_project_dirs(project_dir: Path) -> None:
    """确保项目具备完整的目录结构"""
    for sub in _PROJECT_DIRS:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)


def _scaffold_default_config(project_dir: Path, name: str) -> None:
    """为新项目生成默认配置文件（已存在时仅更新项目名称）"""
    # project.yaml — 始终确保名称正确
    cfg_path = project_dir / "config" / "project.yaml"
    if cfg_path.exists():
        # 已有配置：只更新项目名称，不覆盖其他自定义内容
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("project", {})["name"] = name
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    else:
        # 无配置：从模板生成
        cfg_path.write_text(
            _DEFAULT_PROJECT_YAML.format(name=name),
            encoding="utf-8",
        )

    # 空分镜表
    sb_path = project_dir / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        sb_path.write_text(_DEFAULT_STORYBOARD_CSV, encoding="utf-8")


def _copy_template_if_exists(project_dir: Path, template_dir: Path) -> bool:
    """从模板目录复制内容到项目目录（不覆盖已有文件），返回是否使用了模板"""
    if not template_dir.exists():
        return False

    for src in template_dir.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(template_dir)

        # .example 文件：去掉后缀复制为实际文件
        if src.stem.endswith(".example"):
            dst = project_dir / rel.parent / src.stem
        else:
            dst = project_dir / rel

        # 确保父目录存在
        dst.parent.mkdir(parents=True, exist_ok=True)

        if not dst.exists():
            shutil.copy2(src, dst)
    return True


def list_projects(console):
    root = Path(__file__).resolve().parent.parent
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    active = _active(root)

    from rich.table import Table
    t = Table(title="📂 项目列表")
    t.add_column("", width=3)
    t.add_column("名称", style="cyan")
    t.add_column("路径")
    t.add_column("角色数", justify="center")
    t.add_column("分镜数", justify="center")
    t.add_column("状态")

    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            name = data.get("project", {}).get("name", d.name)
        else:
            name = d.name

        # 统计角色数
        chars_dir = d / "config" / "characters"
        char_count = len([f for f in chars_dir.glob("*.yaml")]) if chars_dir.exists() else 0

        # 统计分镜数
        sb_path = d / "storyboard" / "episodes.csv"
        sb_count = 0
        if sb_path.exists():
            try:
                with open(sb_path, encoding="utf-8") as f:
                    sb_count = sum(1 for _ in csv.DictReader(f))
            except Exception:
                pass

        is_active = d.resolve() == active.resolve()
        t.add_row(
            "→" if is_active else "",
            name, str(d),
            str(char_count), str(sb_count),
            "[green]当前[/green]" if is_active else "",
        )

    console.print(t)


def create_project(name: str, root: Path, console):
    """创建新项目 — 完全独立的目录结构 + 默认配置"""
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    project_dir = projects_dir / name
    if project_dir.exists():
        console.print(f"[red]❌ 项目 '{name}' 已存在[/red]")
        return

    # 1. 创建完整目录结构
    _ensure_project_dirs(project_dir)

    # 2. 尝试从默认模板复制已有内容（角色示例、场景示例等）
    default_dir = projects_dir / DEFAULT_PROJECT
    used_template = _copy_template_if_exists(project_dir, default_dir)

    # 3. 生成默认配置文件（不覆盖模板已复制的）
    _scaffold_default_config(project_dir, name)

    # 4. 设置为活动项目
    (projects_dir / ".active").write_text(str(project_dir))

    console.print(f"[green]✅ 项目 '{name}' 已创建并设为当前[/green]")
    console.print(f"[dim]  路径: {project_dir}[/dim]")
    console.print(f"[dim]  下一步:[/dim]")
    console.print(f"[dim]    1. 编辑 config/characters/ 添加角色[/dim]")
    console.print(f"[dim]    2. 编辑 config/scenes/ 添加场景[/dim]")
    console.print(f"[dim]    3. 编辑 storyboard/episodes.csv 编写分镜剧本[/dim]")
    console.print(f"[dim]    4. drama serve 启动工作台[/dim]")


def switch_project(name: str, root: Path, console):
    projects_dir = root / "projects"
    d = projects_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    # 确保目标项目目录完整
    _ensure_project_dirs(d)
    _scaffold_default_config(d, name)

    (projects_dir / ".active").write_text(str(d))
    console.print(f"[green]✅ 已切换到: {name}[/green]")

    # 显示项目概要
    cfg = d / "config" / "project.yaml"
    if cfg.exists():
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
        proj = data.get("project", {})
        console.print(f"[dim]  集数: {proj.get('episodes', 1)}, 分辨率: {proj.get('resolution', [1280, 720])}[/dim]")

    chars_dir = d / "config" / "characters"
    if chars_dir.exists():
        chars = [f.stem for f in chars_dir.glob("*.yaml") if not f.stem.endswith(".example")]
        if chars:
            console.print(f"[dim]  角色: {', '.join(chars)}[/dim]")


def show_current(root: Path, console):
    active = _active(root)
    cfg = active / "config" / "project.yaml"
    if cfg.exists():
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
        name = data.get("project", {}).get("name", active.name)
    else:
        name = active.name
    console.print(f"[cyan]当前项目:[/cyan] {name}")
    console.print(f"[cyan]路径:[/cyan]     {active}")

    # 显示项目文件统计
    chars_dir = active / "config" / "characters"
    char_count = len([f for f in chars_dir.glob("*.yaml")]) if chars_dir.exists() else 0
    scenes_dir = active / "config" / "scenes"
    scene_count = len([f for f in scenes_dir.glob("*.yaml")]) if scenes_dir.exists() else 0
    sb_path = active / "storyboard" / "episodes.csv"
    sb_count = 0
    if sb_path.exists():
        try:
            with open(sb_path, encoding="utf-8") as f:
                sb_count = sum(1 for _ in csv.DictReader(f))
        except Exception:
            pass
    console.print(f"[cyan]角色:[/cyan] {char_count} 个")
    console.print(f"[cyan]场景:[/cyan] {scene_count} 个")
    console.print(f"[cyan]分镜:[/cyan] {sb_count} 个镜头")


def delete_project(name: str, root: Path, console):
    if name == DEFAULT_PROJECT:
        console.print("[red]❌ 不能删除默认项目[/red]")
        return
    projects_dir = root / "projects"
    d = projects_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    active = _active(root)
    if active.resolve() == d.resolve():
        (projects_dir / ".active").write_text(str(projects_dir / DEFAULT_PROJECT))
    shutil.rmtree(d)
    console.print(f"[green]✅ 项目 '{name}' 已删除[/green]")
