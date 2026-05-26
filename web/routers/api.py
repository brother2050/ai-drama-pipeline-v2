"""API 路由 — 独立工具 + 按需启停

改进项：
- 使用 Pydantic 模型做输入校验
- 路径遍历防护
- 统一重试机制
- 角色/场景 ID 格式校验
"""
from __future__ import annotations

import csv
import logging
import os
import re
import shutil
import sys
import yaml
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile

logger = logging.getLogger(__name__)

# 跨平台文件锁
try:
    import fcntl
    def _file_lock(f):
        fcntl.flock(f, fcntl.LOCK_EX)
    def _file_unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)
except ImportError:
    # Windows: 使用 msvcrt
    import msvcrt
    def _file_lock(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    def _file_unlock(f):
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

# ── 简易 Rate Limiting ──
_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60  # 秒
_RATE_LIMIT_MAX = 120    # 每窗口最大请求数


def _check_rate_limit(client_ip: str) -> None:
    """简易滑动窗口 rate limiting（自动清理过期 IP）"""
    import time
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW

    # 每次调用时清理过期 IP（防止低流量环境下内存泄漏）
    expired_ips = [ip for ip, timestamps in _rate_limit_store.items()
                   if not timestamps or timestamps[-1] < window_start]
    for ip in expired_ips:
        del _rate_limit_store[ip]

    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = []

    # 清理过期记录
    _rate_limit_store[client_ip] = [
        t for t in _rate_limit_store[client_ip] if t > window_start
    ]

    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
        raise HTTPException(429, "请求过于频繁，请稍后再试")

    _rate_limit_store[client_ip].append(now)


def _get_client_ip(request: Request) -> str:
    """获取客户端 IP（支持反向代理）"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _rate_limit_dependency(request: Request):
    """FastAPI 依赖: 自动应用 rate limiting"""
    _check_rate_limit(_get_client_ip(request))


router = APIRouter(dependencies=[Depends(_rate_limit_dependency)])
ROOT = Path(__file__).resolve().parent.parent.parent

# 导入 schemas
sys.path.insert(0, str(ROOT))
from web.schemas import (
    StepRequest, TTSRequest, PostRequest, MusicRequest,
    SubtitleRequest, PipelineRequest, CharacterData, SceneData,
    ProjectCreate, ProjectSwitch, ConfigUpdate,
    StoryboardGenRequest, CharacterGenRequest, SceneGenRequest,
    ChatEditRequest,
    SekoProposalRequest, SekoProposalStatusRequest, SekoProposalModifyRequest,
    SekoImportRequest,
)

# ── 工具函数 ──

def _cfg() -> dict:
    from infra.config import Config
    cfg_path = _cfg_path()
    try:
        data = Config(cfg_path).data
    except Exception:
        # 回退：直接读文件
        if os.path.isfile(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}
    # 移除内部字段
    data.pop("_project_dir", None)
    return data


def _merged_cfg() -> dict:
    """合并项目配置 + 系统配置（工具检测用，确保能拿到 system.yaml 里的 API Key 等）"""
    proj = _cfg()
    sys_path = _sys_cfg_path()
    if os.path.isfile(sys_path):
        with open(sys_path, encoding="utf-8") as f:
            sys_cfg = yaml.safe_load(f) or {}
        return _deep_merge(sys_cfg, proj)
    return proj


def _cfg_path() -> str:
    return str(_proj() / "config" / "project.yaml")


# ── 校验工具 ──

_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$")
_UUID_RE = re.compile(r"^[a-f0-9-]{36}$")
_FILE_RE = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$")

def _check_id(v: str, label: str = "ID") -> None:
    if not _ID_RE.match(v):
        raise HTTPException(400, f"无效的 {label}")

def _check_uuid(v: str) -> None:
    if not _UUID_RE.match(v):
        raise HTTPException(400, "无效的任务 ID")

def _check_filename(v: str) -> None:
    if not _FILE_RE.match(v):
        raise HTTPException(400, "无效的文件名")

def _check_entity_type(v: str) -> None:
    if v not in ("characters", "scenes"):
        raise HTTPException(400, "entity_type 必须是 characters 或 scenes")

def _check_episode(ep: int) -> None:
    if ep < 1:
        raise HTTPException(400, "episode 必须 >= 1")


def _safe_path(base: Path, *parts: str) -> Path:
    """防止路径遍历的安全路径拼接"""
    # 过滤空字符串
    parts = [p for p in parts if p]
    joined = "/".join(parts)
    if not joined:
        return base.resolve()
    # 阻断 .. 遍历
    if ".." in joined.split("/"):
        raise HTTPException(400, "非法路径")
    resolved = (base / joined).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise HTTPException(400, "非法路径")
    return resolved


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并 override 到 base 中（返回新 dict，不修改原对象）"""
    import copy
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _check_tool(name: str, cfg: dict) -> dict:
    """检测单个工具的可用性（委托给 infra.toolcheck）"""
    from infra.toolcheck import check_tool
    return check_tool(name, cfg)


def _submit_task(task, *args, **kwargs) -> dict:
    try:
        result = task.delay(*args, **kwargs)
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
    cfg = _merged_cfg()
    tools = _collect_tools(cfg)
    return {"version": "2.0.0", "tools": tools}


def _collect_tools(cfg: dict) -> dict:
    """收集所有工具状态"""
    tools = {}
    for name in ["redis", "celery", "tts", "comfyui", "lipsync", "llm", "music", "ffmpeg", "seko", "training"]:
        tools[name] = _check_tool(name, cfg)
    return tools


@router.get("/system/env")
def system_env():
    import platform
    return {"os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version()}


# ══════════════════════════════════════════════════════════
# 工具管理
# ══════════════════════════════════════════════════════════

@router.get("/tools")
def list_tools():
    """列出所有工具及其可用状态"""
    cfg = _merged_cfg()
    return {"tools": _collect_tools(cfg)}


@router.get("/tools/{name}")
def check_tool(name: str):
    """检测单个工具状态"""
    cfg = _merged_cfg()
    result = _check_tool(name, cfg)
    return {"name": name, **result}


@router.post("/tools/{name}/test")
def test_tool(name: str):
    """测试三方工具连接（实际发请求验证）"""
    cfg = _merged_cfg()
    result = _check_tool(name, cfg)

    # LLM 特殊处理：不管 enabled 状态，直接测连接
    if name == "llm":
        return _test_llm(cfg, result)

    if not result.get("available"):
        return {"ok": False, "name": name, "message": result.get("reason", "不可用"), **result}

    # 工具可用，再做一次实际连接测试
    try:
        if name == "tts":
            backend = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
            if "mimo" in backend:
                backend_key = backend.replace("-", "_")
                cfg_key = cfg.get("models", {}).get(backend_key, {}).get("api_key", "")
                env_key = os.environ.get("MIMO_API_KEY", "")
                source = "配置文件" if cfg_key else ("环境变量" if env_key else "未配置")
                return {"ok": True, "name": name, "message": f"MIMO API Key ({source})", **result}
            api_url = cfg.get("models", {}).get(backend.replace("-", "_"), {}).get("api_url", "")
            import httpx
            r = httpx.get(api_url, timeout=5)
            return {"ok": True, "name": name, "message": f"连接成功 (HTTP {r.status_code})", **result}

        elif name == "comfyui":
            url = cfg.get("comfyui", {}).get("url", "http://127.0.0.1:8188")
            import httpx
            r = httpx.get(f"{url}/system_stats", timeout=5)
            data = r.json() if r.status_code == 200 else {}
            vram = data.get("devices", [{}])[0].get("vram_total", 0) if data.get("devices") else 0
            msg = f"连接成功" + (f" · VRAM {vram // 1024 // 1024}MB" if vram else "")
            return {"ok": True, "name": name, "message": msg, **result}

        elif name == "lipsync":
            backend = cfg.get("models", {}).get("lip_sync_backend", "musetalk")
            api_url = cfg.get("models", {}).get(backend.replace("-", "_"), {}).get("api_url", "")
            import httpx
            r = httpx.get(api_url, timeout=5)
            return {"ok": True, "name": name, "message": f"{backend} 连接成功 (HTTP {r.status_code})", **result}

        elif name == "music":
            backend = cfg.get("models", {}).get("music_backend", "template")
            if backend == "template":
                import subprocess
                v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
                ver = v.stdout.split("\n")[0] if v.returncode == 0 else "unknown"
                return {"ok": True, "name": name, "message": f"ffmpeg: {ver}", **result}
            api_url = cfg.get("models", {}).get(backend, {}).get("api_url", "")
            import httpx
            r = httpx.get(api_url, timeout=5)
            return {"ok": True, "name": name, "message": f"{backend} 连接成功", **result}

        elif name == "ffmpeg":
            import subprocess
            v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
            ver = v.stdout.split("\n")[0] if v.returncode == 0 else "unknown"
            return {"ok": True, "name": name, "message": ver, **result}

        elif name == "redis":
            import socket
            with socket.create_connection(("127.0.0.1", 6379), timeout=3) as s:
                s.send(b"PING\r\n")
                resp = s.recv(64)
            return {"ok": True, "name": name, "message": f"Redis PONG: {resp.decode().strip()}", **result}

        elif name == "celery":
            from pipeline.celery_app import app
            insp = app.control.inspect(timeout=3)
            active = insp.active() or {}
            workers = list(active.keys())
            return {"ok": True, "name": name, "message": f"Celery Worker: {', '.join(workers) or 'none'}", **result}

        elif name == "training":
            training_cfg = cfg.get("training", {})
            api_url = training_cfg.get("api_url", "")
            if not api_url:
                return {"ok": False, "name": name, "message": "训练服务地址未配置", **result}
            import httpx
            r = httpx.get(api_url, timeout=5)
            return {"ok": True, "name": name, "message": f"FluxGym 连接成功 (HTTP {r.status_code})", **result}

        return {"ok": True, "name": name, "message": "可用", **result}

    except Exception as e:
        return {"ok": False, "name": name, "message": f"测试失败: {e}", **result}


def _test_llm(cfg: dict, result: dict) -> dict:
    """LLM 连接测试（忽略 enabled 开关，直接测）"""
    name = "llm"
    llm_cfg = cfg.get("llm", {})
    base_url = llm_cfg.get("base_url", "")
    backend = llm_cfg.get("backend", "ollama")
    api_key = llm_cfg.get("api_key", "")

    if not base_url:
        return {"ok": False, "name": name, "message": "未配置 API URL", **result}
    if not api_key and backend != "ollama":
        return {"ok": False, "name": name, "message": "未配置 API Key", **result}

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    import httpx
    try:
        if backend == "ollama":
            r = httpx.get(f"{base_url}/api/tags", timeout=5)
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"ok": True, "name": name, "message": f"Ollama 连接成功 · {len(models)} 模型", "models": models, **result}
        else:
            check_url = base_url.rstrip("/")
            if not check_url.endswith("/v1"):
                check_url += "/v1"
            r = httpx.get(f"{check_url}/models", headers=headers, timeout=5)
            if r.status_code in (401, 403):
                return {"ok": False, "name": name, "message": f"API Key 无效 ({r.status_code})", **result}
            if r.status_code == 404:
                return {"ok": False, "name": name, "message": f"接口不存在 (404)，检查 API URL: {check_url}", **result}
            if r.status_code != 200:
                return {"ok": False, "name": name, "message": f"HTTP {r.status_code}", **result}
            data = r.json()
            count = len(data.get("data", []))
            return {"ok": True, "name": name, "message": f"LLM 连接成功 · {count} 模型", **result}
    except httpx.ConnectError:
        return {"ok": False, "name": name, "message": f"连接被拒绝: {base_url}", **result}
    except httpx.TimeoutException:
        return {"ok": False, "name": name, "message": f"连接超时: {base_url}", **result}
    except Exception as e:
        return {"ok": False, "name": name, "message": f"连接失败: {e}", **result}


# ── 单步执行 ──

@router.post("/steps/tts")
def run_step_tts(req: StepRequest):
    """Step 1: TTS"""
    from pipeline.tasks import step_tts
    return _submit_task(step_tts, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/first-frame")
def run_step_first_frame(req: StepRequest):
    """Step 2: 首帧"""
    from pipeline.tasks import step_first_frame
    return _submit_task(step_first_frame, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/video")
def run_step_video(req: StepRequest):
    """Step 3: 视频"""
    from pipeline.tasks import step_video
    return _submit_task(step_video, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/lipsync")
def run_step_lipsync(req: StepRequest):
    """Step 4: 口型同步"""
    from pipeline.tasks import step_lipsync
    return _submit_task(step_lipsync, _cfg_path(), req.episode, req.shot_id)


@router.post("/steps/shot")
def run_step_shot(req: StepRequest):
    """单镜头编排"""
    from pipeline.tasks import shot_task
    shot = _find_shot_for_api(req.episode, req.shot_id)
    if not shot:
        raise HTTPException(404, f"镜头 {req.shot_id} 不存在")
    return _submit_task(shot_task, _cfg_path(), req.episode, shot)


def _find_shot_for_api(episode: int, shot_id: str) -> dict | None:
    sb_path = _proj() / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return None
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ep = int(row.get("episode", 0) or 0)
            except (ValueError, TypeError):
                continue
            if ep == episode and row.get("shot_id") == shot_id:
                return dict(row)
    return None


# ── 独立工具 ──

@router.post("/tools/tts")
def run_tts(req: TTSRequest):
    """独立 TTS"""
    from pipeline.tasks import tts_single_task
    return _submit_task(tts_single_task, _cfg_path(), req.text,
                        req.voice_config, req.emotion, req.language)


@router.post("/tools/portraits")
def gen_portraits():
    """生成定妆照"""
    from pipeline.tasks import portraits_task
    return _submit_task(portraits_task, _cfg_path())


@router.post("/tools/post")
def run_post(req: PostRequest):
    """后期合成"""
    from pipeline.tasks import post_task
    return _submit_task(post_task, _cfg_path(), req.episode, req.vertical)


@router.post("/tools/music")
def run_music(req: MusicRequest):
    """配乐生成"""
    from pipeline.tasks import music_task
    import time
    output = str(_proj() / "output" / f"bgm_{int(time.time())}.wav")
    return _submit_task(music_task, _cfg_path(), req.duration, req.mood, output)


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
    _check_uuid(task_id)
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
    _check_uuid(task_id)
    from pipeline.celery_app import app
    app.control.revoke(task_id, terminate=True)
    return {"status": "cancelled", "task_id": task_id}


# ══════════════════════════════════════════════════════════
# 配置 / 项目 / 角色 / 场景 / 分镜
# ══════════════════════════════════════════════════════════

def _sys_cfg_path() -> str:
    return str(ROOT / "config" / "system.yaml")


@router.get("/system/config")
def get_system_config():
    """读取系统全局配置"""
    path = _sys_cfg_path()
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


@router.post("/system/config")
def update_system_config(data: dict = Body(...)):
    """更新系统全局配置"""
    from infra.config import save_config, load_config
    path = _sys_cfg_path()
    try:
        existing = load_config(path)
    except Exception:
        existing = {}
    merged = _deep_merge(existing, data)
    save_config(path, merged)
    return {"status": "ok"}


@router.get("/config")
def get_config():
    cfg = _cfg()
    return cfg


@router.post("/config")
def update_config(req: ConfigUpdate):
    """更新配置（接受任意 dict）

    兼容两种格式:
    - {"data": {...}} — 新格式
    - {"project": {...}} — 旧格式（直接发送 config dict）
    """
    data = req.get_config_data()
    cfg_path = _cfg_path()
    from infra.config import save_config, load_config
    # 加载现有配置，深度合并后再保存
    try:
        existing = load_config(cfg_path)
    except Exception:
        existing = {}
    merged = _deep_merge(existing, data)
    save_config(cfg_path, merged)
    # 注意: Container 在每次请求/任务时按需创建，下次会自动读取新配置
    return {"status": "ok"}


@router.get("/projects")
def list_projects():
    projects_dir = ROOT / "projects"
    projects_dir.mkdir(exist_ok=True)
    active_file = projects_dir / ".active"
    active_path = active_file.read_text().strip() if active_file.exists() else None
    # 未设置 .active 时默认指向 projects/default/
    if not active_path:
        active_path = str(projects_dir / "default")
    result = []
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            name = data.get("project", {}).get("name", d.name)
        else:
            name = d.name
        result.append({"name": name, "path": str(d), "active": active_path == str(d), "isDefault": d.name == "default"})
    default_name = "默认"
    default_cfg = projects_dir / "default" / "config" / "project.yaml"
    if default_cfg.exists():
        with open(default_cfg, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        default_name = data.get("project", {}).get("name", "默认")
    return {"projects": result, "defaultName": default_name}


@router.post("/projects/new")
def create_project(req: ProjectCreate):
    from scripts.project_mgr import create_project
    from rich.console import Console
    create_project(req.name, ROOT, Console())
    return {"status": "ok", "name": req.name}


@router.post("/projects/switch")
def switch_project(req: ProjectSwitch):
    from scripts.project_mgr import switch_project
    from rich.console import Console
    projects_dir = ROOT / "projects"
    # 直接按目录名匹配
    project_dir = projects_dir / req.name
    if project_dir.exists() and project_dir.is_dir():
        switch_project(req.name, ROOT, Console())
        return {"status": "ok"}
    # 按项目名称匹配（遍历 config/project.yaml）
    for d in projects_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        cfg = d / "config" / "project.yaml"
        if cfg.exists():
            with open(cfg, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if req.name == data.get("project", {}).get("name", ""):
                switch_project(d.name, ROOT, Console())
                return {"status": "ok"}
    raise HTTPException(404, f"项目 '{req.name}' 不存在")


@router.delete("/projects/{name}")
def delete_project(name: str):
    if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff]+$", name):
        raise HTTPException(400, "无效的项目名")
    if name == "default":
        raise HTTPException(400, "不能删除默认项目")
    from scripts.project_mgr import delete_project
    from rich.console import Console
    try:
        delete_project(name, ROOT, Console())
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "name": name}


# ── 通用 YAML CRUD 工厂 ──

_proj_cache: tuple[float, Path] | None = None

def _proj() -> Path:
    """返回当前活动项目目录（带 mtime 缓存）"""
    global _proj_cache
    active_file = ROOT / "projects" / ".active"
    try:
        mt = active_file.stat().st_mtime
    except FileNotFoundError:
        mt = 0.0
    if _proj_cache and _proj_cache[0] == mt:
        return _proj_cache[1]
    d = ROOT / "projects" / "default"
    if active_file.exists():
        p = Path(active_file.read_text().strip())
        if p.exists():
            d = p
    _proj_cache = (mt, d)
    return d


def _yaml_list(yaml_dir: str, entity_key: str) -> list[dict]:
    """通用 YAML 实体列表读取"""
    d = _proj() / "config" / yaml_dir
    if not d.exists():
        return []
    result = []
    for f in d.glob("*.yaml"):
        if f.stem.endswith(".example"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            entity = data.get(entity_key, {})
            if entity.get("id"):
                result.append(entity)
        except Exception:
            continue
    return result


def _yaml_save(yaml_dir: str, entity_key: str, entity_id: str, data: dict,
               db_upsert=None) -> None:
    """通用 YAML 实体保存（YAML + DB 双写）"""
    d = _proj() / "config" / yaml_dir
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{entity_id}.yaml", "w") as f:
        yaml.dump({entity_key: {**data, "id": entity_id}}, f,
                  allow_unicode=True, default_flow_style=False)
    if db_upsert:
        try:
            from infra.database.pool import get_pool
            db_upsert(get_pool(), entity_id, data)
        except Exception as e:
            logger.debug(f"数据库同步跳过: {e}")


def _parse_entity(req) -> tuple[str, dict]:
    """Pydantic 模型 → (entity_id, data)"""
    data = req.model_dump(exclude_none=True)
    return data.pop("id"), data


def _yaml_delete(yaml_dir: str, entity_id: str, label: str, db_delete=None) -> None:
    """通用 YAML 实体删除（文件 + DB）"""
    path = _proj() / "config" / yaml_dir / f"{entity_id}.yaml"
    if not path.exists():
        raise HTTPException(404, f"{label} {entity_id} 不存在")
    path.unlink()
    if db_delete:
        try:
            from infra.database.pool import get_pool
            db_delete(get_pool(), entity_id)
        except Exception as e:
            logger.debug(f"数据库同步跳过: {e}")


@router.get("/characters")
def list_characters():
    return {"characters": _yaml_list("characters", "character")}


@router.post("/characters")
def save_character(req: CharacterData):
    char_id, data = _parse_entity(req)
    from infra.database.characters import upsert as db_up
    _yaml_save("characters", "character", char_id, data, db_upsert=db_up)
    return {"status": "ok", "id": char_id}


@router.delete("/characters/{char_id}")
def delete_character(char_id: str):
    _check_id(char_id, "角色 ID")
    from infra.database.characters import delete as db_del
    _yaml_delete("characters", char_id, "角色", db_delete=db_del)
    return {"status": "ok", "id": char_id}


@router.get("/scenes")
def list_scenes():
    return {"scenes": _yaml_list("scenes", "scene")}


@router.post("/scenes")
def save_scene(req: SceneData):
    scene_id, data = _parse_entity(req)
    from infra.database.scenes import upsert as db_up
    _yaml_save("scenes", "scene", scene_id, data, db_upsert=db_up)
    return {"status": "ok", "id": scene_id}


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str):
    _check_id(scene_id, "场景 ID")
    from infra.database.scenes import delete as db_del
    _yaml_delete("scenes", scene_id, "场景", db_delete=db_del)
    return {"status": "ok", "id": scene_id}


# ── 角色/场景图片上传 ──

@router.post("/assets/{entity_type}/{entity_id}/upload")
async def upload_entity_image(entity_type: str, entity_id: str, file: UploadFile = File(...)):
    """上传角色/场景参考图"""

    _check_entity_type(entity_type)
    _check_id(entity_id)

    # 校验文件类型
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的文件类型: {ext}，允许: {', '.join(allowed)}")

    # 保存到 assets 目录
    asset_dir = _proj() / "assets" / entity_type / entity_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cover{ext}"
    dest = asset_dir / filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 更新 YAML 中的 reference_images
    yaml_dir = "characters" if entity_type == "characters" else "scenes"
    entity_key = "character" if entity_type == "characters" else "scene"
    yaml_path = _proj() / "config" / yaml_dir / f"{entity_id}.yaml"
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        entity = data.get(entity_key, {})
        imgs = entity.get("reference_images") or []
        img_url = f"/api/assets/{entity_type}/{entity_id}/{filename}"
        # 移除同实体的旧 cover URL（不同扩展名），再添加新的
        prefix = f"/api/assets/{entity_type}/{entity_id}/cover"
        imgs = [u for u in imgs if not u.startswith(prefix)]
        imgs.append(img_url)
        entity["reference_images"] = imgs
        data[entity_key] = entity
        with open(yaml_path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    return {"status": "ok", "url": f"/api/assets/{entity_type}/{entity_id}/{filename}"}


@router.get("/assets/{entity_type}/{entity_id}/{filename}")
def get_entity_asset(entity_type: str, entity_id: str, filename: str):
    """访问角色/场景资源文件"""
    from fastapi.responses import FileResponse

    _check_entity_type(entity_type)
    _check_id(entity_id)
    _check_filename(filename)

    file_path = _proj() / "assets" / entity_type / entity_id / filename
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    ext = file_path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))


@router.get("/episodes")
def get_episodes():
    """获取可用集数列表"""
    sb_path = _proj() / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return {"episodes": [1], "current": 1}
    ep_set = set()
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ep = int(row.get("episode", 0) or 0)
            except (ValueError, TypeError):
                continue
            if ep > 0:
                ep_set.add(ep)
    if not ep_set:
        ep_set = {1}
    return {"episodes": sorted(ep_set), "current": min(ep_set)}


@router.get("/episodes/summary")
def get_episodes_summary():
    """批量获取所有集数摘要（镜头数、资源进度），避免 N+1 查询"""
    sb_path = _proj() / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return {"episodes": []}

    # 一次性读取所有数据，按 episode 分组
    ep_shots: dict[int, list[dict]] = {}
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ep = int(row.get("episode", 0) or 0)
            except (ValueError, TypeError):
                continue
            if ep > 0:
                ep_shots.setdefault(ep, []).append(row)

    result = []
    for ep in sorted(ep_shots):
        shots = ep_shots[ep]
        total_dur = sum(int(s.get("duration", 4) or 4) for s in shots)
        done_count = 0
        out_base = _proj() / "output" / f"e{ep:02d}"
        for s in shots:
            sid = s.get("shot_id", "")
            if not sid:
                continue
            shot_dir = out_base / f"s{sid}"
            if (shot_dir / "frame.png").exists() or (shot_dir / "video.mp4").exists():
                done_count += 1
        status = "none" if not shots else "done" if done_count >= len(shots) else "progress" if done_count > 0 else "none"
        result.append({
            "episode": ep,
            "shots": len(shots),
            "duration": total_dur,
            "done": done_count,
            "status": status,
        })
    return {"episodes": result}


@router.get("/storyboard/{episode}")
def get_storyboard(episode: int):
    _check_episode(episode)
    sb_path = _proj() / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return {"episode": episode, "shots": []}
    shots = []
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0) or 0) == episode:
                shots.append(row)
    return {"episode": episode, "shots": shots}


@router.post("/storyboard/{episode}")
def save_storyboard(episode: int, data: dict):
    _check_episode(episode)
    shots = data.get("shots", [])
    if not isinstance(shots, list):
        raise HTTPException(400, "shots 必须是数组")
    if len(shots) > 500:
        raise HTTPException(400, "shots 数组过大，最多 500 个镜头")

    # 校验每个镜头的 shot_id 格式
    for shot in shots:
        sid = shot.get("shot_id", "")
        if sid:
            _check_id(sid, "shot_id")

    sb_path = _proj() / "storyboard" / "episodes.csv"
    sb_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["episode", "shot_id", "scene", "characters", "action", "dialogue",
                  "camera", "shot_type", "duration", "outfit", "emotion",
                  "action_en", "dialogue_en"]
    lock_path = sb_path.with_suffix(".lock")
    with open(lock_path, "w") as lock_f:
        _file_lock(lock_f)
        try:
            existing = []
            if sb_path.exists():
                with open(sb_path, encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if int(row.get("episode", 0) or 0) != episode:
                            existing.append(row)
            with open(sb_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(existing + shots)
        finally:
            _file_unlock(lock_f)

    # 同步更新数据库 shots 表
    try:
        from infra.database.pool import get_pool
        from infra.database.shots import upsert as db_upsert_shot
        pool = get_pool()
        for shot in shots:
            sid = shot.get("shot_id", "")
            if sid:
                db_upsert_shot(pool, episode, sid, shot)
    except Exception as e:
        logger.debug(f"数据库同步跳过: {e}")

    return {"status": "ok", "count": len(shots)}


# ══════════════════════════════════════════════════════════
# LLM 内容生成（异步，通过 Celery）
# ══════════════════════════════════════════════════════════

@router.post("/llm/storyboard")
def llm_generate_storyboard(req: StoryboardGenRequest):
    """AI 生成分镜表（异步，通过 Celery）"""
    cfg = _cfg_path()
    from pipeline.tasks import ai_storyboard_task
    return _submit_task(ai_storyboard_task, cfg, req.episode, req.outline, req.duration, req.append)


@router.post("/llm/characters")
def llm_generate_characters(req: CharacterGenRequest):
    """AI 生成角色（异步，通过 Celery）"""
    cfg = _cfg_path()
    from pipeline.tasks import ai_characters_task
    return _submit_task(ai_characters_task, cfg, req.descriptions)


@router.post("/llm/scenes")
def llm_generate_scenes(req: SceneGenRequest):
    """AI 生成场景（异步，通过 Celery）"""
    cfg = _cfg_path()
    from pipeline.tasks import ai_scenes_task
    return _submit_task(ai_scenes_task, cfg, req.descriptions)


# ══════════════════════════════════════════════════════════
# 管线
# ══════════════════════════════════════════════════════════

@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest):
    from pipeline.tasks import preview_task, produce_task, post_task
    cfg = _cfg_path()
    dispatch = {
        "preview": lambda: _submit_task(preview_task, cfg, req.episode, req.level),
        "produce": lambda: _submit_task(produce_task, cfg, req.episode, vertical=req.vertical),
        "post":    lambda: _submit_task(post_task, cfg, req.episode, req.vertical),
    }
    handler = dispatch.get(req.command)
    if not handler:
        raise HTTPException(400, f"未知命令: {req.command}")
    return handler()


@router.get("/pipeline/status/{episode}")
def pipeline_status(episode: int):
    from flow.episode import get_episode_status
    return get_episode_status(str(_proj()), episode)


# ══════════════════════════════════════════════════════════
# 镜头资源查询 + 文件预览（带路径遍历防护）
# ══════════════════════════════════════════════════════════

@router.get("/shots/{episode}/{shot_id}/resources")
def get_shot_resources(episode: int, shot_id: str):
    """查询镜头已生成的资源"""
    _check_episode(episode)
    _check_id(shot_id, "shot_id")

    out_dir = _safe_path(_proj(), "output", f"e{episode:02d}", f"s{shot_id}")
    if not out_dir.exists():
        return {"shot_id": shot_id, "resources": {}}

    resources = {}
    for fname, key in [("audio.wav", "audio"), ("frame.png", "frame"),
                        ("video.mp4", "video"), ("synced.mp4", "synced")]:
        if (out_dir / fname).exists():
            resources[key] = fname
    return {"shot_id": shot_id, "resources": resources}


@router.get("/files/{episode}/{shot_id}/{filename}")
def get_shot_file(episode: int, shot_id: str, filename: str):
    """预览镜头资源文件（带路径遍历防护）"""
    from fastapi.responses import FileResponse

    _check_episode(episode)
    _check_filename(filename)

    proj = _proj()

    if shot_id == "final":
        # 成片文件
        out_dir = proj / "output" / f"e{episode:02d}" / "final"
        if not out_dir.exists():
            out_dir = proj / "output" / f"e{episode:02d}"
        file_path = _safe_path(out_dir, filename)
    else:
        _check_id(shot_id, "shot_id")
        file_path = _safe_path(proj, "output", f"e{episode:02d}", f"s{shot_id}", filename)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    ext = file_path.suffix.lower()
    media_types = {
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))


@router.get("/project-file/{path:path}")
def get_project_file(path: str):
    """通用项目文件访问（带路径遍历防护）"""
    from fastapi.responses import FileResponse

    proj = _proj()
    file_path = _safe_path(proj, path)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {path}")

    ext = file_path.suffix.lower()
    media_types = {
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))


# ══════════════════════════════════════════════════════════
# 4.4 Worker 状态
# ══════════════════════════════════════════════════════════

@router.get("/system/workers")
def get_worker_status():
    """获取 Celery Worker 状态"""
    try:
        from pipeline.celery_app import app as celery_app
        inspect = celery_app.control.inspect(timeout=0.5)
        active = inspect.active() or {}
        active_tasks = sum(len(v) for v in active.values())
        return {"status": "online", "active": active_tasks, "workers": list(active.keys())}
    except Exception as e:
        logger.debug(f"Worker 状态检查失败: {e}")
        return {"status": "offline", "active": 0, "workers": []}


# ══════════════════════════════════════════════════════════
# 4.2 主体库（共享资产）
# ══════════════════════════════════════════════════════════

def _shared_assets_dir() -> Path:
    """获取全局共享资产目录"""
    d = ROOT / "shared_assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/assets/shared/characters")
def list_shared_characters():
    """获取全局共享角色列表"""
    shared_dir = _shared_assets_dir() / "characters"
    shared_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for yaml_file in sorted(shared_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            data["id"] = yaml_file.stem
            items.append(data)
        except Exception:
            pass
    return {"assets": items}


@router.get("/assets/shared/scenes")
def list_shared_scenes():
    """获取全局共享场景列表"""
    shared_dir = _shared_assets_dir() / "scenes"
    shared_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for yaml_file in sorted(shared_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            data["id"] = yaml_file.stem
            items.append(data)
        except Exception:
            pass
    return {"assets": items}


@router.post("/assets/shared/{entity_type}/{entity_id}/copy")
def copy_asset_to_project(entity_type: str, entity_id: str):
    """从主体库复制到当前项目"""
    _check_entity_type(entity_type)
    _check_id(entity_id)

    shared_dir = _shared_assets_dir() / entity_type
    src = shared_dir / f"{entity_id}.yaml"
    if not src.exists():
        raise HTTPException(404, f"主体库中不存在: {entity_id}")

    proj_dir = _proj() / "config" / entity_type
    proj_dir.mkdir(parents=True, exist_ok=True)
    dst = proj_dir / f"{entity_id}.yaml"
    if dst.exists():
        raise HTTPException(409, f"项目中已存在: {entity_id}")

    shutil.copy2(str(src), str(dst))

    # 复制图片
    src_img = shared_dir / entity_id
    if src_img.is_dir():
        dst_img = proj_dir / entity_id
        shutil.copytree(str(src_img), str(dst_img), dirs_exist_ok=True)

    # 同步数据库
    try:
        data = yaml.safe_load(dst.read_text(encoding="utf-8")) or {}
        entity = data.get(entity_type.rstrip("s"), {})
        if entity_type == "characters":
            from infra.database.characters import upsert as db_up
        else:
            from infra.database.scenes import upsert as db_up
        from infra.database.pool import get_pool
        db_up(get_pool(), entity_id, entity)
    except Exception as e:
        logger.debug(f"数据库同步跳过: {e}")

    return {"ok": True, "message": f"已复制 {entity_id} 到当前项目"}


@router.post("/assets/{entity_type}/{entity_id}/share")
def add_to_shared_library(entity_type: str, entity_id: str):
    """将项目资产添加到全局主体库"""
    _check_entity_type(entity_type)
    _check_id(entity_id)

    proj_dir = _proj() / "config" / entity_type
    src = proj_dir / f"{entity_id}.yaml"
    if not src.exists():
        raise HTTPException(404, f"项目中不存在: {entity_id}")

    shared_dir = _shared_assets_dir() / entity_type
    shared_dir.mkdir(parents=True, exist_ok=True)
    dst = shared_dir / f"{entity_id}.yaml"

    shutil.copy2(str(src), str(dst))

    # 复制图片
    src_img = proj_dir / entity_id
    if src_img.is_dir():
        dst_img = shared_dir / entity_id
        shutil.copytree(str(src_img), str(dst_img), dirs_exist_ok=True)

    return {"ok": True, "message": f"已添加 {entity_id} 到主体库"}


# ══════════════════════════════════════════════════════════
# 3.5 成片预览
# ══════════════════════════════════════════════════════════

@router.get("/shots/{episode}/final/resources")
def get_final_resources(episode: int):
    """获取成片资源状态"""
    _check_episode(episode)
    proj = _proj()
    out_dir = proj / "output" / f"e{episode:02d}" / "final"
    if not out_dir.exists():
        out_dir = proj / "output" / f"e{episode:02d}"
    final_mp4 = out_dir / f"episode_{episode:02d}_final.mp4"
    if not final_mp4.exists():
        candidates = list(out_dir.glob("*final*.mp4"))
        if candidates:
            final_mp4 = candidates[0]
        else:
            return {"resources": {}}
    return {"resources": {"final": final_mp4.name}}


# ══════════════════════════════════════════════════════════
# 4.1 对话式编辑（LLM Chat Edit）
# ══════════════════════════════════════════════════════════

@router.post("/llm/chat-edit")
def llm_chat_edit(req: ChatEditRequest):
    """对话式编辑分镜 — 用自然语言修改分镜表"""
    _check_episode(req.episode)
    cfg = _cfg_path()

    from pipeline.tasks import ai_chat_edit_task
    return _submit_task(ai_chat_edit_task, cfg, req.episode, req.message, req.shots)


# ══════════════════════════════════════════════════════════
# Seko 影视策划案（seko.sensetime.com）
# ══════════════════════════════════════════════════════════

@router.post("/seko/proposal")
def seko_generate_proposal(req: SekoProposalRequest):
    """生成影视策划案（异步提交，返回 task_id）"""
    from api.backends.seko.proposal import generate_proposal
    cfg = _merged_cfg()
    seko_cfg = cfg.get("seko", {})
    result = generate_proposal(req.prompt, api_key=req.api_key, config=seko_cfg)
    if result.get("code") == 200:
        data = result.get("data", {})
        return {"status": "submitted", "task_id": data.get("taskId"), "raw": result}
    raise HTTPException(502, result.get("msg", "策划案生成失败"))


@router.post("/seko/proposal/status")
def seko_proposal_status(req: SekoProposalStatusRequest):
    """查询策划案任务状态（支持轮询等待 + 图片下载）"""
    from api.backends.seko.proposal import (
        check_proposal_status, wait_for_proposal, download_elements_images,
    )
    cfg = _merged_cfg()
    seko_cfg = cfg.get("seko", {})

    if req.wait:
        result = wait_for_proposal(
            req.task_id, api_key=req.api_key, config=seko_cfg, interval=req.interval,
        )
    else:
        result = check_proposal_status(req.task_id, api_key=req.api_key, config=seko_cfg)

    # 任务成功 + 指定下载目录 → 自动下载图片
    downloaded = []
    if req.download_dir and result.get("code") == 200:
        data = result.get("data", {})
        if data.get("taskStatus") == "OK":
            # 特殊值 __project_assets__ → 使用当前项目的 assets 目录
            if req.download_dir == "__project_assets__":
                download_dir = str(_proj() / "assets" / "seko" / req.task_id)
            else:
                download_dir = os.path.join(req.download_dir, req.task_id)
            downloaded = download_elements_images(data, download_dir)

    return {
        "status": result.get("data", {}).get("taskStatus", "UNKNOWN"),
        "task_id": req.task_id,
        "downloaded": downloaded,
        "raw": result,
    }


@router.post("/seko/proposal/modify")
def seko_modify_proposal(req: SekoProposalModifyRequest):
    """修改已有策划案（返回新 task_id）"""
    from api.backends.seko.proposal import modify_proposal
    cfg = _merged_cfg()
    seko_cfg = cfg.get("seko", {})
    result = modify_proposal(req.task_id, req.prompt, api_key=req.api_key, config=seko_cfg)
    if result.get("code") == 200:
        data = result.get("data", {})
        return {"status": "submitted", "task_id": data.get("taskId"), "raw": result}
    raise HTTPException(502, result.get("msg", "策划案修改失败"))


@router.post("/seko/proposal/import")
def seko_import_proposal(req: SekoImportRequest):
    """导入 Seko 策划案到项目（异步，含图片下载）

    解析 Seko 返回的策划案 JSON，将角色/场景/分镜异步导入项目，
    并在后台下载关联图片，避免 HTTP 超时。

    若指定 project_name，则先创建新项目再导入。
    """
    from pipeline.tasks import seko_import_task
    from scripts.project_mgr import create_project
    from rich.console import Console

    # 如果指定了项目名，先创建新项目
    if req.project_name:
        projects_dir = ROOT / "projects"
        project_dir = projects_dir / req.project_name
        if project_dir.exists():
            raise HTTPException(409, f"项目 '{req.project_name}' 已存在")
        create_project(req.project_name, ROOT, Console())

    cfg = _cfg_path()
    return _submit_task(
        seko_import_task, cfg,
        req.proposal_data, req.episode,
        req.import_characters, req.import_scenes,
        req.import_storyboard, req.download_images,
    )
