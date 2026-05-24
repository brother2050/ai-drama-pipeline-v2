"""项目管理 — 纯 Python"""
from __future__ import annotations

import logging
import shutil
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

def _active(root: Path) -> str | None:
    f = root / "projects" / ".active"
    return f.read_text().strip() if f.exists() else None

def list_projects(console):
    root = Path(__file__).resolve().parent.parent
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    active = _active(root)

    from rich.table import Table
    t = Table(title="📂 项目列表")
    t.add_column("", width=3); t.add_column("名称", style="cyan")
    t.add_column("路径"); t.add_column("状态")

    # 根项目
    cfg = root / "config" / "project.yaml"
    if cfg.exists():
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
        name = data.get("project", {}).get("name", "默认项目")
        is_active = active is None
        t.add_row("→" if is_active else "", name, str(root), "[green]当前[/green]" if is_active else "")

    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            name = data.get("project", {}).get("name", d.name)
            is_active = active == str(d)
            t.add_row("→" if is_active else "", name, str(d), "[green]当前[/green]" if is_active else "")

    console.print(t)

def create_project(name: str, root: Path, console):
    projects_dir = root / "projects"
    projects_dir.mkdir(exist_ok=True)
    project_dir = projects_dir / name
    if project_dir.exists():
        console.print(f"[red]❌ 项目 '{name}' 已存在[/red]")
        return

    project_dir.mkdir(parents=True, exist_ok=True)
    for sub in ["config", "storyboard", "story"]:
        src = root / sub
        if src.exists():
            shutil.copytree(src, project_dir / sub)
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
    if name in ("default", "默认"):
        f = projects_dir / ".active"
        if f.exists(): f.unlink()
        console.print("[green]✅ 已切换到默认项目[/green]")
        return
    d = projects_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    (projects_dir / ".active").write_text(str(d))
    console.print(f"[green]✅ 已切换到: {name}[/green]")

def show_current(root: Path, console):
    active = _active(root)
    if active:
        cfg = Path(active) / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            name = data.get("project", {}).get("name", Path(active).name)
            console.print(f"[cyan]当前项目:[/cyan] {name}")
            console.print(f"[cyan]路径:[/cyan]     {active}")
            return
    console.print("[cyan]当前项目:[/cyan] 默认项目")

def delete_project(name: str, root: Path, console):
    projects_dir = root / "projects"
    d = projects_dir / name
    if not d.exists():
        console.print(f"[red]❌ 项目 '{name}' 不存在[/red]")
        return
    active = _active(root)
    if active == str(d):
        (projects_dir / ".active").unlink(missing_ok=True)
    shutil.rmtree(d)
    console.print(f"[green]✅ 项目 '{name}' 已删除[/green]")
