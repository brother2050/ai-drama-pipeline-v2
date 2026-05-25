"""项目管理 — 纯 Python

所有项目（含默认）统一存放在 projects/ 下。
"""
from __future__ import annotations

import logging
import shutil
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "default"


def _active(root: Path) -> Path:
    """返回当前活动项目路径。无 .active 时回退到 projects/default/"""
    f = root / "projects" / ".active"
    if f.exists():
        p = Path(f.read_text().strip())
        if p.exists():
            return p
    return root / "projects" / DEFAULT_PROJECT


def list_projects(console):
    root = Path(__file__).resolve().parent.parent
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    active = _active(root)

    from rich.table import Table
    t = Table(title="📂 项目列表")
    t.add_column("", width=3); t.add_column("名称", style="cyan")
    t.add_column("路径"); t.add_column("状态")

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
        is_active = d.resolve() == active.resolve()
        t.add_row("→" if is_active else "", name, str(d), "[green]当前[/green]" if is_active else "")

    console.print(t)


def create_project(name: str, root: Path, console):
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    project_dir = projects_dir / name
    if project_dir.exists():
        console.print(f"[red]❌ 项目 '{name}' 已存在[/red]")
        return

    # 从默认项目复制模板
    default_dir = projects_dir / DEFAULT_PROJECT
    if default_dir.exists():
        shutil.copytree(default_dir, project_dir)
    else:
        project_dir.mkdir(parents=True, exist_ok=True)
        for sub in ["config", "storyboard", "story"]:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        for sub in ["assets/characters", "assets/scenes", "output"]:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

    cfg_path = project_dir / "config" / "project.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("project", {})["name"] = name
        with open(cfg_path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    (projects_dir / ".active").write_text(str(project_dir))
    console.print(f"[green]✅ 项目 '{name}' 已创建并设为当前[/green]")


def switch_project(name: str, root: Path, console):
    projects_dir = root / "projects"
    d = projects_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    (projects_dir / ".active").write_text(str(d))
    console.print(f"[green]✅ 已切换到: {name}[/green]")


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
