"""API 路由 — 统一入口"""
from __future__ import annotations
import os, json, yaml
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent.parent

def _cfg() -> dict:
    cfg_path = ROOT / "config" / "project.yaml"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}

# ── 系统 ──

@router.get("/system/status")
def system_status():
    cfg = _cfg()
    import socket
    def port_ok(p):
        try:
            with socket.create_connection(("127.0.0.1", p), timeout=2): return True
        except: return False
    return {
        "version": "2.0.0",
        "services": {
            "postgresql": port_ok(5432),
            "redis": port_ok(6379),
            "comfyui": _check_url(cfg.get("comfyui", {}).get("url", "http://127.0.0.1:8188")),
        },
        "config": {"tts": cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")},
    }

def _check_url(url: str) -> bool:
    try:
        import httpx
        return httpx.get(f"{url}/system_stats", timeout=3).status_code == 200
    except: return False

# ── 配置 ──

@router.get("/config")
def get_config():
    return _cfg()

@router.post("/config")
def update_config(data: dict):
    cfg_path = ROOT / "config" / "project.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok"}

# ── 项目 ──

@router.get("/projects")
def list_projects():
    projects_dir = ROOT / "projects"
    projects_dir.mkdir(exist_ok=True)
    active_file = projects_dir / ".active"
    active = active_file.read_text().strip() if active_file.exists() else None
    result = []
    # 根项目
    cfg = ROOT / "config" / "project.yaml"
    if cfg.exists():
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
        result.append({"name": data.get("project", {}).get("name", "默认"), "path": str(ROOT),
                       "active": active is None})
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."): continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            result.append({"name": data.get("project", {}).get("name", d.name),
                           "path": str(d), "active": active == str(d)})
    return {"projects": result}

# ── 分镜 ──

@router.get("/storyboard/{episode}")
def get_storyboard(episode: int):
    sb_path = ROOT / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return {"episode": episode, "shots": []}
    import csv
    shots = []
    with open(sb_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("episode", 0)) == episode:
                shots.append(row)
    return {"episode": episode, "shots": shots}

# ── 管线 ──

class PipelineRequest(BaseModel):
    episode: int
    command: str = "produce"
    level: str = "draft"

@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest):
    import subprocess, sys
    cfg_path = ROOT / "config" / "project.yaml"
    module = {"preview": "pipeline.preview", "produce": "pipeline.producer",
              "post": "post.production"}.get(req.command)
    if not module:
        raise HTTPException(400, f"未知命令: {req.command}")
    args = [sys.executable, "-m", module, "-c", str(cfg_path), "-e", str(req.episode)]
    if req.command == "preview":
        args.extend(["-p", req.level])
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    return {"status": "ok" if r.returncode == 0 else "error", "stdout": r.stdout[-5000:], "stderr": r.stderr[-2000:]}
