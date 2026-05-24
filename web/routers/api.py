"""API 路由 — 独立工具 + 按需启停"""
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


def _url_ok(url: str, path: str = "/") -> bool:
    try:
        import httpx
        return httpx.get(f"{url}{path}", timeout=3).status_code == 200
    except Exception:
        return False


def _check_tool(name: str, cfg: dict) -> dict:
    """检测单个工具的可用性"""
    if name == "tts":
        backend = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
        if "mimo" in backend:
            import os
            ok = bool(os.environ.get("MIMO_API_KEY"))
            return {"available": ok, "backend": backend, "type": "cloud",
                    "reason": "" if ok else "MIMO_API_KEY 未配置"}
        else:
            # 其他 TTS 需要 API 服务
            api_url = cfg.get("models", {}).get(backend.replace("-", "_"), {}).get("api_url", "")
            ok = _url_ok(api_url) if api_url else False
            return {"available": ok, "backend": backend, "type": "api",
                    "url": api_url, "reason": "" if ok else f"{backend} 服务不可达"}

    elif name == "comfyui":
        url = cfg.get("comfyui", {}).get("url", "http://127.0.0.1:8188")
        ok = _url_ok(url, "/system_stats")
        return {"available": ok, "backend": "comfyui", "type": "gpu",
                "url": url, "reason": "" if ok else "ComfyUI 不可达"}

    elif name == "lipsync":
        backend = cfg.get("models", {}).get("lip_sync_backend", "musetalk")
        api_url = cfg.get("models", {}).get(backend.replace("-", "_"), {}).get("api_url", "")
        ok = _url_ok(api_url) if api_url else False
        return {"available": ok, "backend": backend, "type": "gpu",
                "url": api_url, "reason": "" if ok else f"{backend} 服务不可达"}

    elif name == "llm":
        llm_cfg = cfg.get("llm", {})
        if not llm_cfg.get("enabled"):
            return {"available": False, "backend": "disabled", "type": "cloud",
                    "reason": "LLM 未启用"}
        base_url = llm_cfg.get("base_url", "http://localhost:11434")
        ok = _url_ok(base_url, "/api/tags")
        return {"available": ok, "backend": llm_cfg.get("backend", "ollama"), "type": "gpu",
                "url": base_url, "reason": "" if ok else "LLM 服务不可达"}

    elif name == "music":
        backend = cfg.get("models", {}).get("music_backend", "template")
        if backend == "template":
            import shutil
            ok = bool(shutil.which("ffmpeg"))
            return {"available": ok, "backend": "template", "type": "local",
                    "reason": "" if ok else "ffmpeg 未安装"}
        else:
            api_url = cfg.get("models", {}).get(backend, {}).get("api_url", "")
            ok = _url_ok(api_url) if api_url else False
            return {"available": ok, "backend": backend, "type": "gpu",
                    "reason": "" if ok else f"{backend} 服务不可达"}

    elif name == "ffmpeg":
        import shutil
        ok = bool(shutil.which("ffmpeg"))
        return {"available": ok, "backend": "ffmpeg", "type": "local",
                "reason": "" if ok else "ffmpeg 未安装"}

    elif name == "redis":
        ok = _port_ok(6379)
        return {"available": ok, "backend": "redis", "type": "infra",
                "reason": "" if ok else "Redis 未运行"}

    elif name == "celery":
        if not _port_ok(6379):
            return {"available": False, "backend": "celery", "type": "infra",
                    "reason": "Redis 未运行（Celery 依赖 Redis）"}
        try:
            from pipeline.celery_app import app
            insp = app.control.inspect(timeout=2)
            ok = bool(insp.active())
            return {"available": ok, "backend": "celery", "type": "infra",
                    "reason": "" if ok else "Celery Worker 未启动"}
        except Exception:
            return {"available": False, "backend": "celery", "type": "infra",
                    "reason": "Celery 连接失败"}

    return {"available": False, "backend": "unknown", "type": "unknown", "reason": "未知工具"}


def _submit_task(task, *args) -> dict:
    try:
        result = task.delay(*args)
        return {"status": "submitted", "task_id": result.id,
                "poll_url": f"/api/tasks/{result.id}"}
    except Exception as e:
        raise HTTPException(503, f"任务提交失败: {e}")


# ══════════════════════════════════════════════════════════
# 系统
# ══════════════════════════════════════════════════════════

@router.get("/system/status")
def system_status():
    """全量服务状态"""
    cfg = _cfg()
    tools = {}
    for name in ["redis", "celery", "tts", "comfyui", "lipsync", "llm", "music", "ffmpeg"]:
        tools[name] = _check_tool(name, cfg)

    return {"version": "2.0.0", "tools": tools}


@router.get("/system/env")
def system_env():
    from infra.gpu import detect_gpu
    import platform
    gpu = detect_gpu()
    return {"os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(), "gpu": gpu}


# ══════════════════════════════════════════════════════════
# 工具管理 — 独立检测 / 独立使用
# ══════════════════════════════════════════════════════════

@router.get("/tools")
def list_tools():
    """列出所有工具及其可用状态"""
    cfg = _cfg()
    tools = {}
    for name in ["redis", "celery", "tts", "comfyui", "lipsync", "llm", "music", "ffmpeg"]:
        tools[name] = _check_tool(name, cfg)
    return {"tools": tools}


@router.get("/tools/{name}")
def check_tool(name: str):
    """检测单个工具状态"""
    cfg = _cfg()
    result = _check_tool(name, cfg)
    return {"name": name, **result}


# ── 单步执行（每步独立，能跑哪步跑哪步）──

class StepRequest(BaseModel):
    episode: int
    shot_id: str


@router.post("/steps/tts")
def run_step_tts(req: StepRequest):
    """Step 1: TTS — 只需要 TTS 服务"""
    from pipeline.tasks import step_tts
    return _submit_task(step_tts, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/first-frame")
def run_step_first_frame(req: StepRequest):
    """Step 2: 首帧 — 只需要 ComfyUI"""
    from pipeline.tasks import step_first_frame
    return _submit_task(step_first_frame, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/video")
def run_step_video(req: StepRequest):
    """Step 3: 视频 — 需要 ComfyUI + 首帧已存在"""
    from pipeline.tasks import step_video
    return _submit_task(step_video, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/lipsync")
def run_step_lipsync(req: StepRequest):
    """Step 4: 口型同步 — 需要 LipSync + 视频 + 音频"""
    from pipeline.tasks import step_lipsync
    return _submit_task(step_lipsync, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/shot")
def run_step_shot(req: StepRequest):
    """单镜头编排 — 逐步尝试，跳过不可用的步骤"""
    from pipeline.tasks import shot_task
    shot = _find_shot_for_api(req.episode, req.shot_id)
    if not shot:
        raise HTTPException(404, f"镜头 {req.shot_id} 不存在")
    return _submit_task(shot_task, _cfg_path(), req.episode, shot)


def _find_shot_for_api(episode: int, shot_id: str) -> dict | None:
    sb_path = ROOT / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return None
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode and row.get("shot_id") == shot_id:
                return dict(row)
    return None


# ── 独立工具（直接调用，不走编排）──

class TTSRequest(BaseModel):
    text: str
    voice_config: dict | None = None
    emotion: str = "neutral"
    language: str = "zh"


@router.post("/tools/tts")
def run_tts(req: TTSRequest):
    """独立 TTS — 直接合成"""
    from pipeline.tasks import tts_single_task
    return _submit_task(tts_single_task, _cfg_path(), req.text,
                        req.voice_config, req.emotion, req.language)


@router.post("/tools/portraits")
def gen_portraits():
    """生成定妆照"""
    from pipeline.tasks import portraits_task
    return _submit_task(portraits_task, _cfg_path())


class PostRequest(BaseModel):
    episode: int
    vertical: bool = False


@router.post("/tools/post")
def run_post(req: PostRequest):
    """后期合成"""
    from pipeline.tasks import post_task
    return _submit_task(post_task, _cfg_path(), req.episode, req.vertical)


class MusicRequest(BaseModel):
    duration: float
    mood: str = "neutral"


@router.post("/tools/music")
def run_music(req: MusicRequest):
    """配乐生成"""
    from pipeline.tasks import music_task
    output = str(ROOT / "output" / "bgm.wav")
    return _submit_task(music_task, _cfg_path(), req.duration, req.mood, output)


class SubtitleRequest(BaseModel):
    episode: int


@router.post("/tools/subtitle")
def run_subtitle(req: SubtitleRequest):
    """字幕生成"""
    from pipeline.tasks import subtitle_task
    return _submit_task(subtitle_task, _cfg_path(), req.episode)


# ══════════════════════════════════════════════════════════
# Celery 任务查询
# ══════════════════════════════════════════════════════════

@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    from pipeline.celery_app import app
    result = app.AsyncResult(task_id)
    info = result.info if result.info else {}
    state_map = {"PENDING": "pending", "STARTED": "running", "PROGRESS": "running",
                 "SUCCESS": "success", "FAILURE": "failed", "REVOKED": "cancelled"}
    status = state_map.get(result.state, result.state.lower())
    task_info = {
        "task_id": task_id, "status": status,
        "progress": info.get("progress", 0) if isinstance(info, dict) else 0,
        "stage": info.get("stage", "") if isinstance(info, dict) else "",
        "message": info.get("message", "") if isinstance(info, dict) else "",
    }
    if result.state == "SUCCESS":
        task_info["result"] = result.result
    elif result.state == "FAILURE":
        task_info["error"] = str(result.result) if result.result else ""
    return task_info


@router.get("/tasks")
def list_tasks():
    from pipeline.celery_app import app
    try:
        insp = app.control.inspect(timeout=2)
        active = insp.active() or {}
        tasks = []
        for worker, tl in active.items():
            for t in tl:
                tasks.append({"task_id": t.get("id"), "name": t.get("name"),
                              "status": "running", "worker": worker})
        return {"tasks": tasks}
    except Exception:
        return {"tasks": []}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    from pipeline.celery_app import app
    app.control.revoke(task_id, terminate=True)
    return {"status": "cancelled", "task_id": task_id}


# ══════════════════════════════════════════════════════════
# 配置 / 项目 / 角色 / 场景 / 分镜（不变）
# ══════════════════════════════════════════════════════════

@router.get("/config")
def get_config():
    return _cfg()


@router.post("/config")
def update_config(data: dict):
    with open(_cfg_path(), "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    return {"status": "ok"}


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


# ══════════════════════════════════════════════════════════
# 管线（完整流程，通过 Celery）
# ══════════════════════════════════════════════════════════

class PipelineRequest(BaseModel):
    episode: int
    command: str = "produce"
    level: str = "draft"


@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest):
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


@router.get("/pipeline/status/{episode}")
def pipeline_status(episode: int):
    from flow.episode import get_episode_status
    return get_episode_status(str(ROOT), episode)


# ══════════════════════════════════════════════════════════
# 镜头资源查询 + 文件预览
# ══════════════════════════════════════════════════════════

@router.get("/shots/{episode}/{shot_id}/resources")
def get_shot_resources(episode: int, shot_id: str):
    """查询镜头已生成的资源"""
    out_dir = ROOT / "output" / f"e{episode:02d}" / f"s{shot_id}"
    if not out_dir.exists():
        return {"shot_id": shot_id, "resources": {}}

    resources = {}
    if (out_dir / "audio.wav").exists():
        resources["audio"] = "audio.wav"
    if (out_dir / "frame.png").exists():
        resources["frame"] = "frame.png"
    if (out_dir / "video.mp4").exists():
        resources["video"] = "video.mp4"
    if (out_dir / "synced.mp4").exists():
        resources["synced"] = "synced.mp4"

    return {"shot_id": shot_id, "resources": resources}


@router.get("/files/{episode}/{shot_id}/{filename}")
def get_shot_file(episode: int, shot_id: str, filename: str):
    """预览镜头资源文件"""
    from fastapi.responses import FileResponse
    file_path = ROOT / "output" / f"e{episode:02d}" / f"s{shot_id}" / filename
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    # 根据扩展名设置 content-type
    ext = file_path.suffix.lower()
    media_types = {
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))
