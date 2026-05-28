#!/usr/bin/env python3
"""
AI 短剧管线 v2 — 统一 CLI 入口

依赖: Redis + Celery（必选）
启动: python cli.py serve        → Web 工作台
      python cli.py worker       → Celery Worker
      python cli.py all 1        → 一键全流程
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()
ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.network import port_ok as _port_open

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cli")


def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        except ImportError:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _resolve_config(config_path: str | None = None) -> str:
    if config_path:
        return str(Path(config_path).resolve())
    active = ROOT / "projects" / ".active"
    if active.exists():
        d = active.read_text().strip()
        cfg = Path(d) / "config" / "project.yaml"
        if cfg.exists():
            return str(cfg)
    # 回退到默认项目
    cfg = ROOT / "projects" / "default" / "config" / "project.yaml"
    if cfg.exists():
        return str(cfg)
    console.print("[red]❌ 未找到 config/project.yaml，请先初始化默认项目[/red]")
    sys.exit(1)


def _ensure_redis():
    """确保 Redis 运行（必选依赖）"""
    if _port_open(6379):
        return True

    console.print("[yellow]⚠ Redis 未运行，尝试启动...[/yellow]")
    redis = shutil.which("redis-server")
    if redis:
        subprocess.Popen([redis, "--daemonize", "yes"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time; time.sleep(1)
        if _port_open(6379):
            console.print("[green]✅ Redis 已启动[/green]")
            return True

    # macOS Homebrew
    if shutil.which("brew"):
        subprocess.run(["brew", "services", "start", "redis"],
                       capture_output=True, timeout=30)
        import time; time.sleep(1)
        if _port_open(6379):
            return True

    console.print("[red]❌ Redis 启动失败。请手动安装并启动 Redis[/red]")
    console.print("  Ubuntu: sudo apt install redis-server && sudo systemctl start redis")
    console.print("  macOS:  brew install redis && brew services start redis")
    return False


def _ensure_deps():
    """启动前检查"""
    _load_env()
    _ensure_redis()
    _ensure_postgres()


def _ensure_postgres():
    """确保 PostgreSQL 已配置"""
    dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if not dsn:
        console.print("[red]❌ AI_DRAMA_DB_DSN 未配置（PostgreSQL 必须）[/red]")
        console.print("  示例: AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama")
        console.print("  先创建数据库: CREATE DATABASE ai_drama;")
        sys.exit(1)


# ── CLI ──

@click.group()
@click.version_option("2.0.0", prog_name="drama")
def cli():
    """🎬 AI 短剧管线 v2 — 从剧本到成片，一键搞定"""
    pass


@cli.command()
@click.option("-p", "--port", default=8888, help="Web 端口")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--reload", is_flag=True, help="开发模式")
def serve(port, host, reload):
    """启动 Web 工作台"""
    _load_env()
    if not _ensure_redis():
        sys.exit(1)
    console.print(f"\n[bold green]🎬 Web 工作台启动中 — http://localhost:{port}[/bold green]\n")
    console.print("[dim]需要同时启动 worker: python cli.py worker[/dim]\n")
    import uvicorn
    uvicorn.run("web.app:create_app", factory=True, host=host, port=port, reload=reload, log_level="info")


@cli.command()
@click.option("--concurrency", "-c", default=2, help="并发数")
def worker(concurrency):
    """启动 Celery Worker（处理异步任务）"""
    _load_env()
    if not _ensure_redis():
        sys.exit(1)

    celery = shutil.which("celery")
    if not celery:
        console.print("[red]❌ celery 未安装。pip install celery redis[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]🔧 Celery Worker 启动中 (并发: {concurrency})[/bold cyan]\n")
    os.execvp(celery, [
        celery, "-A", "pipeline.celery_app", "worker",
        "--loglevel=info", f"--concurrency={concurrency}",
        "-Q", "drama",
        "--pool=threads",  # AI 任务 IO 密集，用线程池
    ])


@cli.command()
def status():
    """检查所有服务状态"""
    _load_env()
    table = Table(title="🎬 服务状态", show_lines=True)
    table.add_column("服务", style="cyan")
    table.add_column("状态", justify="center")
    table.add_column("端口/地址", justify="center")
    table.add_column("说明")

    # Redis（必选）
    redis = _port_open(6379)
    table.add_row("Redis", "[green]✅[/green]" if redis else "[red]❌ 必选[/red]",
                   "6379", "任务队列（必选）")

    # PostgreSQL（必选）
    pg_ok = False
    pg_dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
    if pg_dsn:
        try:
            import psycopg2
            conn = psycopg2.connect(pg_dsn, connect_timeout=3)
            conn.close()
            pg_ok = True
        except Exception:
            pass
    table.add_row("PostgreSQL", "[green]✅[/green]" if pg_ok else "[red]❌ 必选[/red]",
                   pg_dsn.split("@")[-1] if pg_dsn else "未配置", "数据库（必选）")

    # Celery Worker
    celery_ok = False
    if redis:
        try:
            from pipeline.celery_app import app
            insp = app.control.inspect(timeout=2)
            active = insp.active()
            celery_ok = bool(active)
        except Exception:
            pass
    table.add_row("Celery Worker", "[green]✅[/green]" if celery_ok else "[red]❌ 未启动[/red]",
                   "-", "异步任务处理（必选）")

    # ComfyUI
    import yaml
    cfg_path = _resolve_config()
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}
    comfyui_url = cfg.get("comfyui", {}).get("url", "http://127.0.0.1:8188")
    try:
        import httpx
        api_key = cfg.get("comfyui", {}).get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = httpx.get(f"{comfyui_url}/system_stats", timeout=3, headers=headers)
        comfyui_ok = r.status_code == 200
    except Exception:
        comfyui_ok = False
    table.add_row("ComfyUI", "[green]✅[/green]" if comfyui_ok else "[yellow]⚠[/yellow]",
                   comfyui_url, "图片/视频生成")

    # TTS
    tts = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
    if "mimo" in tts:
        key = os.environ.get("MIMO_API_KEY", "")
        table.add_row("MiMo TTS", "[green]✅[/green]" if key else "[yellow]⚠ 未配置[/yellow]",
                       "云 API", "语音合成（免费）")

    console.print(table)
    if not redis or not celery_ok:
        console.print("\n[red]⚠ Redis 和 Celery Worker 是必选依赖[/red]")
        console.print("  1. 启动 Redis: redis-server --daemonize yes")
        console.print("  2. 启动 Worker: python cli.py worker")


@cli.command()
@click.argument("episode", type=int, default=1)
@click.argument("level", type=click.Choice(["draft", "standard", "high"]), default="draft")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--force", is_flag=True, help="强制覆盖已有文件")
def preview(episode, level, config_path, force):
    """快速预览（通过 Celery 异步执行）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 预览 第{episode}集 ({level})[/bold cyan]\n")
    if not _run_via_celery("pipeline.preview", cfg, episode, level, force=force):
        sys.exit(1)


@cli.command()
@click.argument("episode", type=int)
@click.option("-c", "--config", "config_path", default=None)
@click.option("--force", is_flag=True, help="强制覆盖已有文件")
def produce(episode, config_path, force):
    """完整生产（通过 Celery 异步执行）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 生产 第{episode}集[/bold cyan]\n")
    if not _run_via_celery("pipeline.produce", cfg, episode, force=force):
        sys.exit(1)


@cli.command()
@click.argument("episode", type=int, default=1)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
def post(episode, vertical, config_path):
    """后期合成"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 后期合成 第{episode}集[/bold cyan]\n")
    if not _run_via_celery("pipeline.post", cfg, episode, vertical=vertical):
        sys.exit(1)


@cli.command("all")
@click.argument("episode", type=int, default=1)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--force", is_flag=True, help="强制覆盖已有文件")
def run_all(episode, vertical, config_path, force):
    """一键全流程（preview → produce → post）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]━━━ 全流程 第{episode}集 ━━━[/bold cyan]\n")
    for i, (label, task_name) in enumerate([
        ("预览", "pipeline.preview"),
        ("生产", "pipeline.produce"),
        ("后期", "pipeline.post"),
    ], 1):
        console.print(f"[bold][{i}/3] {label}[/bold]")
        if task_name == "pipeline.post":
            ok = _run_via_celery(task_name, cfg, episode, vertical=vertical)
        elif task_name == "pipeline.produce":
            ok = _run_via_celery(task_name, cfg, episode, force=force)
        else:
            ok = _run_via_celery(task_name, cfg, episode, force=force)
        if not ok:
            console.print(f"\n[red]❌ 流程在「{label}」步骤失败，已终止[/red]")
            sys.exit(1)
    console.print("\n[bold green]✅ 全流程完成！[/bold green]")


def _run_via_celery(task_name: str, config_path: str, *args, **kwargs) -> bool:
    """通过 Celery 提交任务并等待完成。返回 True 表示成功，False 表示失败。"""
    from pipeline.celery_app import app
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

    # 导入任务模块以注册
    import pipeline.tasks  # noqa: F401

    task = app.send_task(task_name, args=[config_path, *args], kwargs=kwargs)

    console.print(f"[dim]任务已提交: {task.id}[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        ptask = progress.add_task("等待中...", total=100)

        while not task.ready():
            try:
                info = task.info if task.info else {}
                if isinstance(info, dict):
                    pct = info.get("progress", 0)
                    msg = info.get("message", "")
                    progress.update(ptask, completed=pct, description=msg or "处理中...")
            except Exception:
                pass
            import time; time.sleep(0.5)

        # 最终结果
        if task.successful():
            result = task.result
            progress.update(ptask, completed=100, description="[green]✅ 完成[/green]")
            if isinstance(result, dict):
                console.print(f"[dim]结果: {result}[/dim]")
            return True
        else:
            progress.update(ptask, description="[red]❌ 失败[/red]")
            console.print(f"[red]任务失败: {task.result}[/red]")
            return False


@cli.command()
@click.option("-c", "--config", "config_path", default=None)
def portraits(config_path):
    """生成定妆照（通过 Celery）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print("\n[bold cyan]🎨 生成定妆照[/bold cyan]\n")
    if not _run_via_celery("pipeline.portraits", cfg):
        sys.exit(1)


# ── 项目管理 ──

@cli.group()
def project():
    """项目管理"""
    pass


@project.command("list")
def project_list():
    from scripts.project_mgr import list_projects
    list_projects(console)


@project.command("new")
@click.argument("name")
def project_new(name):
    from scripts.project_mgr import create_project
    create_project(name, ROOT, console)


@project.command("switch")
@click.argument("name")
def project_switch(name):
    from scripts.project_mgr import switch_project
    switch_project(name, ROOT, console)


@project.command("current")
def project_current():
    from scripts.project_mgr import show_current
    show_current(ROOT, console)


@project.command("delete")
@click.argument("name")
@click.confirmation_option(prompt="确认删除？")
def project_delete(name):
    from scripts.project_mgr import delete_project
    delete_project(name, ROOT, console)


@cli.command()
def env():
    """显示环境信息"""
    import platform
    from infra.gpu import get_generation_config
    gen = get_generation_config()
    console.print(f"[cyan]OS:[/cyan]     {platform.system()} {platform.release()}")
    console.print(f"[cyan]Python:[/cyan] {platform.python_version()}")
    console.print("[cyan]GPU:[/cyan]    由三方工具管理（本地不检测）")
    console.print(f"[cyan]生成参数:[/cyan] {gen.get('resolution')} / steps={gen.get('image_steps')} / frames={gen.get('video_frames')}")
    if gen.get("note", "").startswith("未配置"):
        console.print(f"[yellow]提示:[/yellow] 建议在 config/system.yaml 中添加 generation 段自定义参数")
    console.print(f"[cyan]Redis:[/cyan]  {'✅ 运行中' if _port_open(6379) else '❌ 未运行'}")


@cli.command()
@click.option("--logs", is_flag=True)
@click.option("--cache", is_flag=True)
def clean(logs, cache):
    """清理日志和缓存"""
    if logs:
        log_dir = ROOT / "logs"
        if log_dir.exists():
            for f in log_dir.glob("*.log"):
                f.write_text("")
        console.print("[green]✅ 日志已清理[/green]")
    if cache:
        for d in [ROOT / ".pytest_cache", ROOT / "__pycache__"]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        console.print("[green]✅ 缓存已清理[/green]")
    if not logs and not cache:
        console.print("[yellow]请指定: --logs 或 --cache[/yellow]")


# ── AI 生成 ──

@cli.group()
def generate():
    """🤖 AI 内容生成（需要 LLM 服务）"""
    pass


def _get_llm(config_path: str | None = None):
    """获取 LLM 实例"""
    _load_env()
    cfg_file = _resolve_config(config_path)
    from infra.config import Config
    cfg = Config(cfg_file)

    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("enabled"):
        console.print("[red]❌ LLM 未启用。请在 project.yaml 中设置 llm.enabled: true[/red]")
        sys.exit(1)

    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container
    cont = Container(cfg.data)
    try:
        return cont.get("llm"), cfg, cfg_file
    except Exception as e:
        console.print(f"[red]❌ LLM 初始化失败: {e}[/red]")
        sys.exit(1)


@generate.command("storyboard")
@click.argument("episode", type=int, default=1)
@click.option("-o", "--outline", default=None, help="大纲文件路径（txt/md）")
@click.option("--text", default=None, help="直接输入大纲文本")
@click.option("-d", "--duration", type=int, default=90, help="目标时长（秒，默认 90）")
@click.option("-c", "--config", "config_path", default=None)
@click.option("--append", is_flag=True, help="追加到现有分镜表（不覆盖）")
def gen_storyboard(episode, outline, text, duration, config_path, append):
    """📝 从剧情大纲生成分镜表"""
    # 读取大纲
    if text:
        outline_text = text
    elif outline:
        p = Path(outline)
        if not p.exists():
            console.print(f"[red]❌ 文件不存在: {outline}[/red]")
            sys.exit(1)
        outline_text = p.read_text(encoding="utf-8")
    else:
        console.print("[yellow]请提供大纲: --outline <文件> 或 --text <文本>[/yellow]")
        sys.exit(1)

    if not outline_text.strip():
        console.print("[red]❌ 大纲为空[/red]")
        sys.exit(1)

    llm, cfg, cfg_file = _get_llm(config_path)

    # 加载已有角色和场景
    from engines.llm_generator import generate_storyboard
    project_dir = Path(cfg_file).parent.parent
    characters = _load_yaml_entities(project_dir / "config" / "characters", "character")
    scenes = _load_yaml_entities(project_dir / "config" / "scenes", "scene")

    console.print(f"\n[bold cyan]📝 生成分镜表 — 第{episode}集[/bold cyan]")
    console.print(f"[dim]大纲: {len(outline_text)} 字 | 目标: {duration}s | 角色: {len(characters)} | 场景: {len(scenes)}[/dim]\n")

    shots = generate_storyboard(llm, outline_text, characters, scenes, episode, duration)

    if not shots:
        console.print("[red]❌ 生成失败，未获得有效分镜[/red]")
        sys.exit(1)

    # 保存
    sb_path = project_dir / "storyboard" / "episodes.csv"
    _save_storyboard_csv(sb_path, shots, episode, append)

    total_sec = sum(int(s.get("duration", 4)) for s in shots)
    console.print(f"\n[bold green]✅ 生成完成！[/bold green]")
    console.print(f"  镜头数: {len(shots)}")
    console.print(f"  总时长: {total_sec} 秒 ({total_sec/60:.1f} 分钟)")
    console.print(f"  保存至: {sb_path}")

    # 显示预览表
    _print_shots_preview(shots)


@generate.command("characters")
@click.option("-d", "--desc", multiple=True, required=True, help="角色描述（可多次指定）")
@click.option("-c", "--config", "config_path", default=None)
def gen_characters(desc, config_path):
    """👤 从描述生成角色配置"""
    llm, cfg, cfg_file = _get_llm(config_path)
    from engines.llm_generator import generate_characters

    console.print(f"\n[bold cyan]👤 生成角色配置[/bold cyan]")
    console.print(f"[dim]共 {len(desc)} 个角色描述[/dim]\n")

    chars = generate_characters(llm, list(desc))
    if not chars:
        console.print("[red]❌ 生成失败[/red]")
        sys.exit(1)

    # 保存
    project_dir = Path(cfg_file).parent.parent
    char_dir = project_dir / "config" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)

    from infra.config import save_yaml
    for char in chars:
        cid = char.get("id", "unknown")
        path = char_dir / f"{cid}.yaml"
        save_yaml(path, {"character": char})
        console.print(f"  ✅ {char.get('name', '?')} ({cid}) → {path.name}")

    console.print(f"\n[bold green]✅ 生成 {len(chars)} 个角色[/bold green]")


@generate.command("scenes")
@click.option("-d", "--desc", multiple=True, required=True, help="场景描述（可多次指定）")
@click.option("-c", "--config", "config_path", default=None)
def gen_scenes(desc, config_path):
    """🏔️ 从描述生成场景配置"""
    llm, cfg, cfg_file = _get_llm(config_path)
    from engines.llm_generator import generate_scenes

    console.print(f"\n[bold cyan]🏔️ 生成场景配置[/bold cyan]")
    console.print(f"[dim]共 {len(desc)} 个场景描述[/dim]\n")

    scene_list = generate_scenes(llm, list(desc))
    if not scene_list:
        console.print("[red]❌ 生成失败[/red]")
        sys.exit(1)

    project_dir = Path(cfg_file).parent.parent
    scene_dir = project_dir / "config" / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)

    from infra.config import save_yaml
    for scene in scene_list:
        sid = scene.get("id", "unknown")
        path = scene_dir / f"{sid}.yaml"
        save_yaml(path, {"scene": scene})
        console.print(f"  ✅ {scene.get('name', '?')} ({sid}) → {path.name}")

    console.print(f"\n[bold green]✅ 生成 {len(scene_list)} 个场景[/bold green]")


@generate.command("all")
@click.argument("episode", type=int, default=1)
@click.option("-o", "--outline", required=True, help="大纲文件路径")
@click.option("-d", "--duration", type=int, default=90, help="目标时长（秒）")
@click.option("-c", "--config", "config_path", default=None)
def gen_all(episode, outline, duration, config_path):
    """🚀 一键生成：大纲 → 角色 + 场景 + 分镜"""
    p = Path(outline)
    if not p.exists():
        console.print(f"[red]❌ 文件不存在: {outline}[/red]")
        sys.exit(1)

    llm, cfg, cfg_file = _get_llm(config_path)
    outline_text = p.read_text(encoding="utf-8")

    console.print(f"\n[bold cyan]━━━ AI 全量生成 第{episode}集 ━━━[/bold cyan]\n")

    # 1) 让 LLM 从大纲中提取角色和场景描述，然后生成配置
    from engines.llm_generator import generate_storyboard, generate_characters, generate_scenes

    # 先生成分镜（会自动使用已有角色/场景）
    project_dir = Path(cfg_file).parent.parent
    characters = _load_yaml_entities(project_dir / "config" / "characters", "character")
    scenes = _load_yaml_entities(project_dir / "config" / "scenes", "scene")

    console.print("[bold][1/3] 生成分镜表...[/bold]")
    shots = generate_storyboard(llm, outline_text, characters, scenes, episode, duration)

    if shots:
        sb_path = project_dir / "storyboard" / "episodes.csv"
        _save_storyboard_csv(sb_path, shots, episode, False)
        console.print(f"  ✅ {len(shots)} 个镜头")
    else:
        console.print("  ⚠ 分镜生成失败")

    console.print("\n[bold green]✅ 全量生成完成！[/bold green]")

    if shots:
        total_sec = sum(int(s.get("duration", 4)) for s in shots)
        console.print(f"  分镜: {len(shots)} 镜头, {total_sec}秒")
        _print_shots_preview(shots)


def _load_yaml_entities(directory: Path, key: str) -> list[dict]:
    """加载目录下所有 YAML 实体"""
    import yaml
    if not directory.exists():
        return []
    result = []
    for f in directory.glob("*.yaml"):
        if f.stem.endswith(".example"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            entity = data.get(key, {})
            if entity.get("id"):
                result.append(entity)
        except Exception:
            continue
    return result


def _save_storyboard_csv(path: Path, shots: list[dict], episode: int, append: bool):
    """保存分镜到 CSV（委托给 engines.storyboard）"""
    from engines.storyboard import save_storyboard
    save_storyboard(path, shots, episode, append)


def _print_shots_preview(shots: list[dict]):
    """打印分镜预览表"""
    table = Table(title="分镜预览", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("场景", width=12)
    table.add_column("角色", width=12)
    table.add_column("动作", width=25)
    table.add_column("台词", width=20)
    table.add_column("景别", width=8)
    table.add_column("情绪", width=8)
    table.add_column("时长", width=4, justify="right")

    for shot in shots[:20]:  # 最多显示 20 个
        table.add_row(
            shot.get("shot_id", "?"),
            shot.get("scene", ""),
            shot.get("characters", ""),
            (shot.get("action", "")[:22] + "...") if len(shot.get("action", "")) > 22 else shot.get("action", ""),
            (shot.get("dialogue", "")[:17] + "...") if len(shot.get("dialogue", "")) > 17 else shot.get("dialogue", ""),
            shot.get("shot_type", ""),
            shot.get("emotion", ""),
            str(shot.get("duration", "")),
        )

    if len(shots) > 20:
        table.add_row("...", "", "", f"还有 {len(shots)-20} 个镜头", "", "", "", "")

    console.print(table)


if __name__ == "__main__":
    cli()
