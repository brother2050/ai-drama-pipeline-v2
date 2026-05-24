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
import socket
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

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cli")


# ── 工具函数 ──

def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


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
    cfg = ROOT / "config" / "project.yaml"
    if cfg.exists():
        return str(cfg)
    console.print("[red]❌ 未找到 config/project.yaml[/red]")
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
        r = httpx.get(f"{comfyui_url}/system_stats", timeout=3)
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
def preview(episode, level, config_path):
    """快速预览（通过 Celery 异步执行）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 预览 第{episode}集 ({level})[/bold cyan]\n")
    _run_via_celery("pipeline.preview", cfg, episode, level)


@cli.command()
@click.argument("episode", type=int)
@click.option("-c", "--config", "config_path", default=None)
def produce(episode, config_path):
    """完整生产（通过 Celery 异步执行）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 生产 第{episode}集[/bold cyan]\n")
    _run_via_celery("pipeline.produce", cfg, episode)


@cli.command()
@click.argument("episode", type=int, default=1)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
def post(episode, vertical, config_path):
    """后期合成"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]🎬 后期合成 第{episode}集[/bold cyan]\n")
    _run_via_celery("pipeline.post", cfg, episode, vertical=vertical)


@cli.command("all")
@click.argument("episode", type=int, default=1)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
def run_all(episode, vertical, config_path):
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
            _run_via_celery(task_name, cfg, episode, vertical=vertical)
        elif task_name == "pipeline.produce":
            _run_via_celery(task_name, cfg, episode)
        else:
            _run_via_celery(task_name, cfg, episode)
    console.print("\n[bold green]✅ 全流程完成！[/bold green]")


def _run_via_celery(task_name: str, config_path: str, *args, **kwargs):
    """通过 Celery 提交任务并等待完成"""
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
        else:
            progress.update(ptask, description="[red]❌ 失败[/red]")
            console.print(f"[red]任务失败: {task.result}[/red]")


@cli.command()
@click.option("-c", "--config", "config_path", default=None)
def portraits(config_path):
    """生成定妆照（通过 Celery）"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print("\n[bold cyan]🎨 生成定妆照[/bold cyan]\n")
    _run_via_celery("pipeline.portraits", cfg)


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
    from infra.gpu import detect_gpu
    gpu = detect_gpu()
    console.print(f"[cyan]OS:[/cyan]     {platform.system()} {platform.release()}")
    console.print(f"[cyan]Python:[/cyan] {platform.python_version()}")
    console.print(f"[cyan]GPU:[/cyan]    {gpu['name']} ({gpu['vram_mb']}MB)" if gpu["available"] else "[cyan]GPU:[/cyan]    不可用（API 模式不受影响）")
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


if __name__ == "__main__":
    cli()
