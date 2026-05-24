"""API 路由 — Celery 异步任务 + 进度轮询"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent.parent


# ── 工具函数 ──

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
    except Exception:
        return False


def _celery_inspect():
    """检查 Celery worker 状态"""
    try:
        from pipeline.celery_app import app
        insp = app.control.inspect(timeout=2)
        active = insp.active()
        return bool(active)
    except Exception:
        return False


def _submit_task(task, *args) -> dict:
    """提交 Celery 任务，返回标准化响应"""
    try:
        result = task.delay(*args)
        return {
            "status": "submitted",
            "task_id": result.id,
            "poll_url": f"/api/tasks/{result.id}",
        }
    except Exception as e:
        raise HTTPException(503, f"任务提交失败（Redis/Celery 不可用）: {e}")


# ── 系统 ──

@router.get("/system/status")
def system_status():
    cfg = _cfg()
    redis_ok = _port_ok(6379)
    celery_ok = _celery_inspect() if redis_ok else False
    return {
        "version": "2.0.0",
        "services": {
            "redis": redis_ok,
            "celery_worker": celery_ok,
            "comfyui": _url_ok(cfg.get("comfyui", {}).get("url", "http://127.0.0.1:8188")),
        },
        "config": {
            "tts": cfg.get("models", {}).get("tts_backend", "mimo-voicedesign"),
            "lipsync": cfg.get("models", {}).get("lip_sync_backend", "musetalk"),
        },
    }


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


# ── 配置 ──

@router.get("/config")
def get_config():
    return _cfg()


@router.post("/config")
def update_config(data: dict):
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
        result.append({"name": data.get("project", {}).get("name", "默认"),
                       "path": str(ROOT), "active": active is None})
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            result.append({"name": data.get("project", {}).get("name", d.name),
                           "path": str(d), "active": active == str(d)})
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
    with open(chars_dir / f"{char_id}.yaml", "w") as f:
        yaml.dump({"character": data}, f, allow_unicode=True, default_flow_style=False)
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
    with open(scenes_dir / f"{scene_id}.yaml", "w") as f:
        yaml.dump({"scene": data}, f, allow_unicode=True, default_flow_style=False)
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

    existing = []
    if sb_path.exists():
        with open(sb_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if int(row.get("episode", 0)) != episode:
                    existing.append(row)

    fieldnames = ["episode", "shot_id", "scene", "characters", "action", "dialogue",
                  "camera", "shot_type", "duration", "outfit", "emotion",
                  "action_en", "dialogue_en"]
    with open(sb_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing + shots)
    return {"status": "ok", "count": len(shots)}


# ── 管线任务（Celery 异步） ──

class PipelineRequest(BaseModel):
    episode: int
    command: str = "produce"
    level: str = "draft"


@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest):
    """提交管线任务到 Celery，立即返回 task_id"""
    from pipeline.tasks import preview_task, produce_task, post_task

    task_map = {
        "preview": (preview_task, [req.episode, req.level]),
        "produce": (produce_task, [req.episode]),
        "post": (post_task, [req.episode]),
    }

    entry = task_map.get(req.command)
    if not entry:
        raise HTTPException(400, f"未知命令: {req.command}")

    task_func, extra_args = entry
    return _submit_task(task_func, _cfg_path(), *extra_args)


@router.post("/pipeline/run-sync")
def run_pipeline_sync(req: PipelineRequest):
    """同步执行（兼容旧模式，仅用于调试/短任务）"""
    module = {"preview": "pipeline.preview", "produce": "pipeline.producer",
              "post": "post.production"}.get(req.command)
    if not module:
        raise HTTPException(400, f"未知命令: {req.command}")
    cmd = [sys.executable, "-m", module, "-c", _cfg_path(), "-e", str(req.episode)]
    if req.command == "preview":
        cmd.extend(["-p", req.level])
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    return {"status": "ok" if r.returncode == 0 else "error",
            "stdout": r.stdout[-5000:], "stderr": r.stderr[-2000:]}


@router.get("/pipeline/status/{episode}")
def pipeline_status(episode: int):
    from flow.episode import get_episode_status
    return get_episode_status(str(ROOT), episode)


# ── 任务查询（Celery 结果） ──

@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    """查询 Celery 任务状态（前端轮询）"""
    from pipeline.celery_app import app
    result = app.AsyncResult(task_id)

    info = result.info if result.info else {}

    # Celery 状态映射
    state_map = {
        "PENDING": "pending",
        "STARTED": "running",
        "PROGRESS": "running",
        "SUCCESS": "success",
        "FAILURE": "failed",
        "REVOKED": "cancelled",
    }

    status = state_map.get(result.state, result.state.lower())
    progress = info.get("progress", 0) if isinstance(info, dict) else 0
    message = info.get("message", "") if isinstance(info, dict) else ""
    stage = info.get("stage", "") if isinstance(info, dict) else ""

    task_info = {
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "stage": stage,
        "message": message,
    }

    if result.state == "SUCCESS":
        task_info["result"] = result.result
    elif result.state == "FAILURE":
        task_info["error"] = str(result.result) if result.result else ""
        task_info["traceback"] = str(result.traceback or "")[-2000:]

    return task_info


@router.get("/tasks")
def list_tasks():
    """列出活跃任务"""
    from pipeline.celery_app import app
    try:
        insp = app.control.inspect(timeout=2)
        active = insp.active() or {}
        scheduled = insp.scheduled() or {}
        tasks = []
        for worker, task_list in active.items():
            for t in task_list:
                tasks.append({
                    "task_id": t.get("id"),
                    "name": t.get("name"),
                    "status": "running",
                    "worker": worker,
                })
        for worker, task_list in scheduled.items():
            for t in task_list:
                tasks.append({
                    "task_id": t.get("id", {}).get("id") if isinstance(t.get("id"), dict) else t.get("id"),
                    "name": t.get("name"),
                    "status": "scheduled",
                    "worker": worker,
                })
        return {"tasks": tasks}
    except Exception as e:
        return {"tasks": [], "error": str(e)}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    """取消任务"""
    from pipeline.celery_app import app
    app.control.revoke(task_id, terminate=True)
    return {"status": "cancelled", "task_id": task_id}


# ── 工具 ──

@router.post("/tools/portraits")
def gen_portraits():
    """生成定妆照（异步）"""
    from pipeline.tasks import portraits_task
    return _submit_task(portraits_task, _cfg_path())
