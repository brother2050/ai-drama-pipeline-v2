#!/usr/bin/env python3
"""
AI 短剧管线 v2 — 统一 CLI 入口

用法:
    drama serve                    启动 Web 工作台
    drama status                   检查服务状态
    drama setup                    环境检测
    drama preview 1 draft          快速预览
    drama produce 1                完整生产
    drama post 1 --vertical        后期合成+横转竖
    drama all 1                    一键全流程
    drama project list             项目管理
    drama portraits                生成定妆照

无需 pip install，直接运行: python cli.py serve
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

# 确保项目根在 sys.path
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _run_module(module: str, *args, config_path: str | None = None):
    cfg = _resolve_config(config_path)
    cmd = [sys.executable, "-m", module, "-c", cfg, *args]
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        console.print(f"[red]❌ 执行失败 (exit {r.returncode})[/red]")
        sys.exit(r.returncode)


def _ensure_deps():
    """自动启动 PostgreSQL/Redis（如需要）"""
    _load_env()
    # 检查是否需要 DB
    cfg_path = _resolve_config()
    import yaml
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}

    # Redis（Celery 需要）
    if cfg.get("celery", {}).get("enabled", False) and not _port_open(6379):
        console.print("[yellow]⚠ Redis 未运行，尝试启动...[/yellow]")
        redis = shutil.which("redis-server")
        if redis:
            subprocess.Popen([redis, "--daemonize", "yes"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time; time.sleep(1)


# ── CLI 命令 ──

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
    _ensure_deps()
    console.print(f"\n[bold green]🎬 Web 工作台启动中 — http://localhost:{port}[/bold green]\n")
    import uvicorn
    uvicorn.run("web.app:create_app", factory=True, host=host, port=port, reload=reload, log_level="info")


@cli.command()
def status():
    """检查所有服务状态"""
    _load_env()
    table = Table(title="🎬 服务状态", show_lines=True)
    table.add_column("服务", style="cyan")
    table.add_column("状态", justify="center")
    table.add_column("端口/地址", justify="center")
    table.add_column("说明")

    # PostgreSQL
    pg = _port_open(5432)
    table.add_row("PostgreSQL", "[green]✅[/green]" if pg else "[yellow]⚠[/yellow]", "5432", "数据存储（可选）")

    # Redis
    redis = _port_open(6379)
    table.add_row("Redis", "[green]✅[/green]" if redis else "[yellow]⚠[/yellow]", "6379", "任务队列（可选）")

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

    # Web
    web_port = cfg.get("server", {}).get("port", 8888)
    web = _port_open(web_port)
    table.add_row("Web 工作台", "[green]✅[/green]" if web else "[yellow]⚠[/yellow]", str(web_port), "操作界面")

    console.print(table)
    if not web:
        console.print("\n[yellow]💡 运行 `drama serve` 启动工作台[/yellow]")


@cli.command()
@click.option("--check-only", is_flag=True, help="仅检测不安装")
def setup(check_only):
    """环境检测与初始化"""
    _load_env()
    console.print("\n[bold cyan]🔍 环境检测[/bold cyan]\n")

    import platform
    import json

    # 系统
    t = Table(title="💻 系统")
    t.add_column("项目", style="cyan"); t.add_column("值")
    t.add_row("OS", f"{platform.system()} {platform.release()} ({platform.machine()})")
    t.add_row("Python", f"{platform.python_version()} ({sys.executable})")
    console.print(t)

    # GPU
    from infra.gpu import detect_gpu
    gpu = detect_gpu()
    gt = Table(title="🎮 GPU")
    gt.add_column("项目", style="cyan"); gt.add_column("值")
    gt.add_row("GPU", gpu["name"])
    gt.add_row("显存", f"{gpu['vram_mb']} MB" if gpu["vram_mb"] else "N/A")
    gt.add_row("状态", "[green]✅ 可用[/green]" if gpu["available"] else "[yellow]⚠ 不可用（API 模式不受影响）[/yellow]")
    console.print(gt)

    # 依赖
    deps = [("yaml", "PyYAML"), ("fastapi", "FastAPI"), ("uvicorn", "Uvicorn"),
            ("httpx", "HTTPX"), ("click", "Click"), ("rich", "Rich"), ("PIL", "Pillow")]
    dt = Table(title="📦 依赖")
    dt.add_column("包", style="cyan"); dt.add_column("状态")
    missing = []
    for mod, name in deps:
        try:
            m = __import__(mod.replace("-", "_"))
            v = getattr(m, "__version__", "installed")
            dt.add_row(name, f"[green]✅ {v}[/green]")
        except ImportError:
            dt.add_row(name, "[red]❌ 缺失[/red]")
            missing.append(name)
    console.print(dt)

    if missing and not check_only:
        console.print(f"[yellow]安装缺失依赖: {', '.join(missing)}[/yellow]")
        subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=False)
    elif not missing:
        console.print("[green]✅ 所有依赖已就绪[/green]")


@cli.command()
@click.argument("episode", type=int, default=1)
@click.argument("level", type=click.Choice(["draft", "standard", "high"]), default="draft")
@click.option("-c", "--config", "config_path", default=None)
def preview(episode, level, config_path):
    """快速预览"""
    _ensure_deps()
    console.print(f"\n[bold cyan]🎬 预览 第{episode}集 ({level})[/bold cyan]\n")
    _run_module("pipeline.preview", "-e", str(episode), "-p", level, config_path=config_path)


@cli.command()
@click.argument("episode", type=int)
@click.option("-c", "--config", "config_path", default=None)
def produce(episode, config_path):
    """完整生产"""
    _ensure_deps()
    console.print(f"\n[bold cyan]🎬 生产 第{episode}集[/bold cyan]\n")
    _run_module("pipeline.producer", "-e", str(episode), config_path=config_path)


@cli.command()
@click.argument("episode", type=int, default=1)
@click.option("--vertical", is_flag=True, help="横转竖")
@click.option("-c", "--config", "config_path", default=None)
def post(episode, vertical, config_path):
    """后期合成"""
    _ensure_deps()
    args = ["-e", str(episode)]
    if vertical:
        args.append("--vertical")
    console.print(f"\n[bold cyan]🎬 后期合成 第{episode}集[/bold cyan]\n")
    _run_module("post.production", *args, config_path=config_path)


@cli.command("all")
@click.argument("episode", type=int, default=1)
@click.option("-c", "--config", "config_path", default=None)
def run_all(episode, config_path):
    """一键全流程"""
    _ensure_deps()
    cfg = _resolve_config(config_path)
    console.print(f"\n[bold cyan]━━━ 全流程 第{episode}集 ━━━[/bold cyan]\n")
    for i, (label, module) in enumerate([
        ("预览", "pipeline.preview"),
        ("生产", "pipeline.producer"),
        ("后期", "post.production"),
    ], 1):
        console.print(f"[bold][{i}/3] {label}[/bold]")
        subprocess.run([sys.executable, "-m", module, "-c", cfg, "-e", str(episode)], cwd=str(ROOT))
    console.print("\n[bold green]✅ 全流程完成！[/bold green]")


@cli.command()
@click.option("-c", "--config", "config_path", default=None)
def portraits(config_path):
    """生成定妆照"""
    _ensure_deps()
    console.print("\n[bold cyan]🎨 生成定妆照[/bold cyan]\n")
    _run_module("pipeline.portraits", config_path=config_path)


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


@cli.command()
@click.option("--concurrency", "-c", default=2, help="并发数（≥2）")
def worker(concurrency):
    """启动 Celery Worker"""
    _load_env()
    _ensure_deps()
    if concurrency < 2:
        console.print("[yellow]⚠ concurrency 必须 ≥2[/yellow]")
        concurrency = 2
    celery = shutil.which("celery")
    if not celery:
        console.print("[red]❌ celery 未安装。pip install celery redis[/red]")
        sys.exit(1)
    os.execvp(celery, [celery, "-A", "pipeline.celery_app", "worker",
                       "--loglevel=info", f"--concurrency={concurrency}"])


if __name__ == "__main__":
    cli()
