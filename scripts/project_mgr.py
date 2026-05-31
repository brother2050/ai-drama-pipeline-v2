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

# ── 风格/题材预设 ──
STYLE_PRESETS = {
    "cinematic": "电影质感 — 专业打光、宽银幕构图、电影色调",
    "anime": "动漫风格 — 日系画风、鲜艳色彩、夸张表情",
    "realistic": "写实风格 — 真实光影、自然色彩、纪录片质感",
    "noir": "黑色电影 — 暗调光影、高对比度、冷峻氛围",
    "fantasy": "奇幻风格 — 魔法元素、华丽特效、异世界感",
    "vintage": "复古风格 — 胶片质感、暖色调、怀旧氛围",
    "minimalist": "极简风格 — 干净画面、留白构图、淡雅色调",
    "cyberpunk": "赛博朋克 — 霓虹灯光、科技感、暗色调",
}

GENRE_PRESETS = {
    "urban": "都市情感 — 现代城市背景、职场/恋爱/家庭",
    "suspense": "悬疑推理 — 悬念迭起、推理破案、心理博弈",
    "romance": "甜蜜恋爱 — 浪漫邂逅、甜蜜互动、情感纠葛",
    "action": "动作热血 — 激烈打斗、追逐场面、英雄主义",
    "comedy": "轻松喜剧 — 幽默搞笑、反转误会、欢乐日常",
    "horror": "惊悚恐怖 — 阴森氛围、恐怖元素、心理压迫",
    "scifi": "科幻未来 — 太空/未来/科技、赛博元素",
    "historical": "古装历史 — 古代背景、宫廷/武侠/历史",
    "campus": "校园青春 — 校园生活、青春成长、同学情谊",
    "family": "家庭温情 — 亲情温暖、家庭矛盾、成长治愈",
}

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
# 系统级配置（ComfyUI、TTS、LLM 等）请编辑 config/system.yaml

project:
  name: "{name}"
  episodes: 1
  fps: 24
  resolution: [1280, 720]
  style: "{style}"
  genre: "{genre}"

# 定妆照配置
# portraits:
#   auto_outfit: false  # 管线自动生成 outfit 参考图（默认 true，设为 false 仅生成主图）

# 项目级覆盖（可选，取消注释可覆盖系统配置）
# comfyui:
#   url: "http://192.168.1.100:8188"
# llm:
#   enabled: true
"""

# 默认分镜表模板（空表头）
_DEFAULT_STORYBOARD_CSV = """\
episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion,action_en,dialogue_en,language
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
    casual:
      description: "（填写日常服装描述）"
      reference_images: []
    formal:
      description: "（填写正式场合服装描述，可选）"
      reference_images: []
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
    from infra.config import ProjectPaths
    ProjectPaths(project_dir).ensure_dirs()


def _scaffold_default_config(project_dir: Path, name: str, style: str = "cinematic", genre: str = "urban") -> None:
    """为新项目生成默认配置文件（已存在时仅更新项目名称和风格）"""
    from infra.config import ProjectPaths, save_yaml
    paths = ProjectPaths(project_dir)

    # project.yaml — 始终确保名称和风格正确
    cfg_path = paths.project_yaml
    if cfg_path.exists():
        # 已有配置：只更新项目名称和风格，不覆盖其他自定义内容
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("project", {})["name"] = name
        data["project"]["style"] = style
        data["project"]["genre"] = genre
        save_yaml(cfg_path, data)
    else:
        # 无配置：从模板生成
        cfg_path.write_text(
            _DEFAULT_PROJECT_YAML.format(name=name, style=style, genre=genre),
            encoding="utf-8",
        )

    # 空分镜表
    sb_path = paths.storyboard_csv
    if not sb_path.exists():
        sb_path.write_text(_DEFAULT_STORYBOARD_CSV, encoding="utf-8")



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
        from infra.config import ProjectPaths
        dp = ProjectPaths(d)
        cfg = dp.project_yaml
        if cfg.exists():
            with open(cfg, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            name = data.get("project", {}).get("name", d.name)
        else:
            name = d.name

        # 统计角色数
        chars_dir = dp.characters_dir
        char_count = len([f for f in chars_dir.glob("*.yaml")]) if chars_dir.exists() else 0

        # 统计分镜数
        sb_path = dp.storyboard_csv
        sb_count = 0
        if sb_path.exists():
            try:
                with open(sb_path, encoding="utf-8") as f:
                    sb_count = sum(1 for _ in csv.DictReader(f))
            except Exception as e:
                logger.debug(f"CSV 计数跳过: {e}")
        is_active = d.resolve() == active.resolve()
        t.add_row(
            "→" if is_active else "",
            name, str(d),
            str(char_count), str(sb_count),
            "[green]当前[/green]" if is_active else "",
        )

    console.print(t)


def create_project(name: str, root: Path, console, style: str = "cinematic", genre: str = "urban"):
    """创建新项目 — 干净的目录结构 + 项目配置（不带模板数据）"""
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    project_dir = projects_dir / name
    if project_dir.exists():
        console.print(f"[red]❌ 项目 '{name}' 已存在[/red]")
        return

    # 1. 创建完整目录结构
    _ensure_project_dirs(project_dir)

    # 2. 生成项目配置（只写 project.yaml + 空分镜表，不复制模板数据）
    _scaffold_default_config(project_dir, name, style=style, genre=genre)

    # 3. 设置为活动项目
    (projects_dir / ".active").write_text(str(project_dir), encoding="utf-8")

    console.print(f"[green]✅ 项目 '{name}' 已创建并设为当前[/green]")
    console.print(f"[dim]  路径: {project_dir}[/dim]")
    console.print(f"[dim]  风格: {style} | 题材: {genre}[/dim]")
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

    (projects_dir / ".active").write_text(str(d), encoding="utf-8")
    console.print(f"[green]✅ 已切换到: {name}[/green]")

    # 显示项目概要
    from infra.config import ProjectPaths
    dp = ProjectPaths(d)
    cfg = dp.project_yaml
    if cfg.exists():
        with open(cfg, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        proj = data.get("project", {})
        style = proj.get('style', 'cinematic')
        genre = proj.get('genre', 'urban')
        console.print(f"[dim]  集数: {proj.get('episodes', 1)}, 分辨率: {proj.get('resolution', [1280, 720])}[/dim]")
        console.print(f"[dim]  风格: {style}, 题材: {genre}[/dim]")

    chars_dir = dp.characters_dir
    if chars_dir.exists():
        chars = [f.stem for f in chars_dir.glob("*.yaml") if not f.stem.endswith(".example")]
        if chars:
            console.print(f"[dim]  角色: {', '.join(chars)}[/dim]")


def show_current(root: Path, console):
    active = _active(root)
    from infra.config import ProjectPaths
    dp = ProjectPaths(active)
    cfg = dp.project_yaml
    if cfg.exists():
        with open(cfg, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        name = data.get("project", {}).get("name", active.name)
    else:
        name = active.name
    console.print(f"[cyan]当前项目:[/cyan] {name}")
    console.print(f"[cyan]路径:[/cyan]     {active}")

    # 显示项目文件统计
    chars_dir = dp.characters_dir
    char_count = len([f for f in chars_dir.glob("*.yaml")]) if chars_dir.exists() else 0
    scenes_dir = dp.scenes_dir
    scene_count = len([f for f in scenes_dir.glob("*.yaml")]) if scenes_dir.exists() else 0
    sb_path = dp.storyboard_csv
    sb_count = 0
    if sb_path.exists():
        try:
            with open(sb_path, encoding="utf-8") as f:
                sb_count = sum(1 for _ in csv.DictReader(f))
        except Exception as e:
            logger.debug(f"CSV 计数跳过: {e}")
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
        (projects_dir / ".active").write_text(str(projects_dir / DEFAULT_PROJECT), encoding="utf-8")

    # 清理数据库中属于该项目的记录（避免孤立数据干扰重建同名项目）
    _cleanup_project_db(d)

    shutil.rmtree(d)
    console.print(f"[green]✅ 项目 '{name}' 已删除[/green]")


def _cleanup_project_db(project_dir: Path) -> None:
    """清理数据库中属于该项目的所有记录"""
    try:
        import os
        os.environ.setdefault("AI_DRAMA_DB_DSN", "")
        dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
        if not dsn:
            return
        import psycopg2
        from infra.config import ProjectPaths
        conn = psycopg2.connect(dsn, connect_timeout=3)
        try:
            cur = conn.cursor()
            # 按项目配置目录匹配角色/场景（YAML 文件删除前执行）
            proj_str = str(project_dir)
            paths = ProjectPaths(project_dir)

            # 清理 comfyui_assets（按 project_dir 匹配）
            cur.execute("DELETE FROM comfyui_assets WHERE project_dir = %s", (proj_str,))

            # 清理 characters/scenes/shots/generation_status
            # 通过读取项目 YAML 文件获取 ID 列表
            chars_dir = paths.characters_dir
            if chars_dir.exists():
                for f in chars_dir.glob("*.yaml"):
                    if f.stem.endswith(".example"):
                        continue
                    try:
                        import yaml
                        with open(f, encoding="utf-8") as fh:
                            data = yaml.safe_load(fh) or {}
                        cid = data.get("character", {}).get("id", f.stem)
                        cur.execute("DELETE FROM characters WHERE id = %s", (cid,))
                    except Exception:
                        logger.debug(f"{type(e).__name__}: {e}")

            scenes_dir = paths.scenes_dir
            if scenes_dir.exists():
                for f in scenes_dir.glob("*.yaml"):
                    if f.stem.endswith(".example"):
                        continue
                    try:
                        import yaml
                        with open(f, encoding="utf-8") as fh:
                            data = yaml.safe_load(fh) or {}
                        sid = data.get("scene", {}).get("id", f.stem)
                        cur.execute("DELETE FROM scenes WHERE id = %s", (sid,))
                    except Exception:
                        logger.debug(f"{type(e).__name__}: {e}")

            # 清理 shots 和 generation_status（按 episode 匹配）
            sb_path = paths.storyboard_csv
            episodes_seen = set()
            if sb_path.exists():
                import csv as _csv
                try:
                    with open(sb_path, encoding="utf-8") as fh:
                        for row in _csv.DictReader(fh):
                            try:
                                ep = int(row.get("episode", 0) or 0)
                                if ep > 0:
                                    episodes_seen.add(ep)
                            except (ValueError, TypeError):
                                logger.debug(f"{type(e).__name__}: {e}")
                except Exception:
                    logger.debug(f"{type(e).__name__}: {e}")

            # 也从 episodes 表补充（CSV 可能已被清空/修改，但 DB 中仍有记录）
            try:
                cur.execute("SELECT episode FROM episodes")
                for row in cur.fetchall():
                    ep = row[0] if not hasattr(row, 'keys') else row['episode']
                    if ep and ep > 0:
                        episodes_seen.add(ep)
            except Exception:
                logger.debug(f"{type(e).__name__}: {e}")

            for ep in episodes_seen:
                cur.execute("DELETE FROM generation_status WHERE episode = %s", (ep,))
                cur.execute("DELETE FROM shots WHERE episode = %s", (ep,))
                cur.execute("DELETE FROM episodes WHERE episode = %s", (ep,))

            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"数据库清理跳过（DB 不可用）: {e}")
