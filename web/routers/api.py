"""API 路由 — 完整版"""
from __future__ import annotations
import csv, json, os, subprocess, sys, yaml
from pathlib import Path
from typing import Any
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

def _cfg_path() -> str:
    return str(ROOT / "config" / "project.yaml")

def _port_ok(port: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False

def _url_ok(url: str) -> bool:
    try:
        import httpx
        return httpx.get(f"{url}/system_stats", timeout=3).status_code == 200
    except:
        return False

# ── 系统 ──

@router.get("/system/status")
def system_status():
    cfg = _cfg()
    return {
        "version": "2.0.0",
        "services": {
            "postgresql": _port_ok(5432),
            "redis": _port_ok(6379),
            "comfyui": _url_ok(cfg.get("comfyui", {}).get("url", "http://127.0.0.1:8188")),
        },
        "config": {
            "tts": cfg.get("models", {}).get("tts_backend", "mimo-voicedesign"),
            "lipsync": cfg.get("models", {}).get("lip_sync_backend", "musetalk"),
        },
    }

# ── 配置 ──

@router.get("/config")
def get_config():
    return _cfg()

@router.post("/config")
def update_config(data: dict):
    import yaml
    with open(_cfg_path(), "w") as f:
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
    cfg = ROOT / "config" / "project.yaml"
    if cfg.exists():
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
        result.append({"name": data.get("project", {}).get("name", "默认"), "path": str(ROOT), "active": active is None})
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            result.append({"name": data.get("project", {}).get("name", d.name), "path": str(d), "active": active == str(d)})
    return {"projects": result}

@router.post("/projects/new")
def create_project(data: dict):
    name = data.get("name", "")
    if not name:
        raise HTTPException(400, "name required")
    from scripts.project_mgr import create_project
    from rich.console import Console
    create_project(name, ROOT, Console())
    return {"status": "ok", "name": name}

@router.post("/projects/switch")
def switch_project(data: dict):
    name = data.get("name", "")
    from scripts.project_mgr import switch_project
    from rich.console import Console
    switch_project(name, ROOT, Console())
    return {"status": "ok"}

# ── 角色 ──

@router.get("/characters")
def list_characters():
    chars_dir = ROOT / "config" / "characters"
    result = []
    if chars_dir.exists():
        for f in chars_dir.glob("*.yaml"):
            if f.stem.endswith(".example"):
                continue
            with open(f) as fh:
                data = yaml.safe_load(fh) or {}
            char = data.get("character", {})
            if char.get("id"):
                result.append(char)
    return {"characters": result}

@router.post("/characters")
def save_character(data: dict):
    char_id = data.get("id", "")
    if not char_id:
        raise HTTPException(400, "id required")
    chars_dir = ROOT / "config" / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"character": data}
    with open(chars_dir / f"{char_id}.yaml", "w") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok", "id": char_id}

# ── 场景 ──

@router.get("/scenes")
def list_scenes():
    scenes_dir = ROOT / "config" / "scenes"
    result = []
    if scenes_dir.exists():
        for f in scenes_dir.glob("*.yaml"):
            if f.stem.endswith(".example"):
                continue
            with open(f) as fh:
                data = yaml.safe_load(fh) or {}
            scene = data.get("scene", {})
            if scene.get("id"):
                result.append(scene)
    return {"scenes": result}

@router.post("/scenes")
def save_scene(data: dict):
    scene_id = data.get("id", "")
    if not scene_id:
        raise HTTPException(400, "id required")
    scenes_dir = ROOT / "config" / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"scene": data}
    with open(scenes_dir / f"{scene_id}.yaml", "w") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok", "id": scene_id}

# ── 分镜 ──

@router.get("/storyboard/{episode}")
def get_storyboard(episode: int):
    sb_path = ROOT / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return {"episode": episode, "shots": []}
    shots = []
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode:
                shots.append(row)
    return {"episode": episode, "shots": shots}

@router.post("/storyboard/{episode}")
def save_storyboard(episode: int, data: dict):
    shots = data.get("shots", [])
    sb_path = ROOT / "storyboard" / "episodes.csv"
    sb_path.parent.mkdir(parents=True, exist_ok=True)

    # 保留其他集的镜头
    existing = []
    if sb_path.exists():
        with open(sb_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if int(row.get("episode", 0)) != episode:
                    existing.append(row)

    fieldnames = ["episode", "shot_id", "scene", "characters", "action", "dialogue",
                  "camera", "shot_type", "duration", "outfit", "emotion",
                  "action_en", "dialogue_en"]
    all_shots = existing + shots
    with open(sb_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_shots)
    return {"status": "ok", "count": len(shots)}

# ── 管线 ──

class PipelineRequest(BaseModel):
    episode: int
    command: str = "produce"
    level: str = "draft"

@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest):
    module = {"preview": "pipeline.preview", "produce": "pipeline.producer",
              "post": "post.production"}.get(req.command)
    if not module:
        raise HTTPException(400, f"未知命令: {req.command}")
    args = [sys.executable, "-m", module, "-c", _cfg_path(), "-e", str(req.episode)]
    if req.command == "preview":
        args.extend(["-p", req.level])
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    return {"status": "ok" if r.returncode == 0 else "error", "stdout": r.stdout[-5000:], "stderr": r.stderr[-2000:]}

@router.get("/pipeline/status/{episode}")
def pipeline_status(episode: int):
    from flow.episode import get_episode_status
    return get_episode_status(str(ROOT), episode)

# ── 工具 ──

@router.post("/tools/portraits")
def gen_portraits():
    args = [sys.executable, "-m", "pipeline.portraits", "-c", _cfg_path()]
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    return {"status": "ok" if r.returncode == 0 else "error", "stdout": r.stdout[-3000:]}

@router.get("/system/env")
def system_env():
    from infra.gpu import detect_gpu
    import platform
    gpu = detect_gpu()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "gpu": gpu,
    }
