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
import sys
import yaml
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request

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
    return str(_active_project_dir() / "config" / "project.yaml")



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
# 工具管理
# ══════════════════════════════════════════════════════════

@router.get("/tools")
def list_tools():
    """列出所有工具及其可用状态"""
    cfg = _merged_cfg()
    tools = {}
    for name in ["redis", "celery", "tts", "comfyui", "lipsync", "llm", "music", "ffmpeg"]:
        tools[name] = _check_tool(name, cfg)
    return {"tools": tools}


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
                return {"ok": True, "name": name, "message": f"MIMO API Key 已配置", **result}
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
    sb_path = _active_project_dir() / "storyboard" / "episodes.csv"
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
    output = str(_active_project_dir() / "output" / f"bgm_{int(time.time())}.wav")
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
    # 校验 task_id 格式（UUID）
    if not re.match(r"^[a-f0-9-]{36}$", task_id):
        raise HTTPException(400, "无效的任务 ID")
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
    if not re.match(r"^[a-f0-9-]{36}$", task_id):
        raise HTTPException(400, "无效的任务 ID")
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

def _active_project_dir() -> Path:
    """返回当前活动项目目录"""
    active_file = ROOT / "projects" / ".active"
    if active_file.exists():
        d = Path(active_file.read_text().strip())
        if d.exists():
            return d
    return ROOT / "projects" / "default"


def _yaml_list(yaml_dir: str, entity_key: str) -> list[dict]:
    """通用 YAML 实体列表读取"""
    d = _active_project_dir() / "config" / yaml_dir
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
    d = _active_project_dir() / "config" / yaml_dir
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


def _yaml_delete(yaml_dir: str, entity_id: str, label: str, db_delete=None) -> None:
    """通用 YAML 实体删除（文件 + DB）"""
    path = _active_project_dir() / "config" / yaml_dir / f"{entity_id}.yaml"
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
    data = req.model_dump(exclude_none=True)
    char_id = data.pop("id")
    from infra.database.characters import upsert as db_up
    _yaml_save("characters", "character", char_id, data, db_upsert=db_up)
    return {"status": "ok", "id": char_id}


@router.delete("/characters/{char_id}")
def delete_character(char_id: str):
    if not re.match(r"^[a-zA-Z0-9_-]+$", char_id):
        raise HTTPException(400, "无效的角色 ID")
    from infra.database.characters import delete as db_del
    _yaml_delete("characters", char_id, "角色", db_delete=db_del)
    return {"status": "ok", "id": char_id}


@router.get("/scenes")
def list_scenes():
    return {"scenes": _yaml_list("scenes", "scene")}


@router.post("/scenes")
def save_scene(req: SceneData):
    data = req.model_dump(exclude_none=True)
    scene_id = data.pop("id")
    from infra.database.scenes import upsert as db_up
    _yaml_save("scenes", "scene", scene_id, data, db_upsert=db_up)
    return {"status": "ok", "id": scene_id}


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str):
    if not re.match(r"^[a-zA-Z0-9_-]+$", scene_id):
        raise HTTPException(400, "无效的场景 ID")
    from infra.database.scenes import delete as db_del
    _yaml_delete("scenes", scene_id, "场景", db_delete=db_del)
    return {"status": "ok", "id": scene_id}


@router.get("/episodes")
def get_episodes():
    """获取可用集数列表"""
    sb_path = _active_project_dir() / "storyboard" / "episodes.csv"
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


@router.get("/storyboard/{episode}")
def get_storyboard(episode: int):
    if episode < 1:
        raise HTTPException(400, "episode 必须 >= 1")
    sb_path = _active_project_dir() / "storyboard" / "episodes.csv"
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
    if episode < 1:
        raise HTTPException(400, "episode 必须 >= 1")
    shots = data.get("shots", [])
    if not isinstance(shots, list):
        raise HTTPException(400, "shots 必须是数组")
    if len(shots) > 500:
        raise HTTPException(400, "shots 数组过大，最多 500 个镜头")

    # 校验每个镜头的 shot_id 格式
    for shot in shots:
        sid = shot.get("shot_id", "")
        if sid and not re.match(r"^[a-zA-Z0-9_-]+$", sid):
            raise HTTPException(400, f"无效的 shot_id: {sid}")

    sb_path = _active_project_dir() / "storyboard" / "episodes.csv"
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
                        if int(row.get("episode", 0)) != episode:
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
# LLM 内容生成
# ══════════════════════════════════════════════════════════

def _get_llm_for_api():
    """获取 LLM 实例（API 层）"""
    cfg = _merged_cfg()
    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("enabled"):
        raise HTTPException(400, "LLM 未启用。请在 project.yaml 中设置 llm.enabled: true")

    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container
    cont = Container(cfg)
    try:
        return cont.get("llm")
    except Exception as e:
        raise HTTPException(503, f"LLM 不可用: {e}")


@router.post("/llm/storyboard")
def llm_generate_storyboard(req: StoryboardGenRequest):
    """AI 生成分镜表"""
    llm = _get_llm_for_api()
    from engines.llm_generator import generate_storyboard

    # 加载已有角色和场景
    proj_dir = _active_project_dir()
    characters = _yaml_list("characters", "character")
    scenes = _yaml_list("scenes", "scene")

    shots = generate_storyboard(llm, req.outline, characters, scenes, req.episode, req.duration)
    if not shots:
        raise HTTPException(500, "LLM 未能生成有效分镜")

    # 保存到 CSV
    sb_path = proj_dir / "storyboard" / "episodes.csv"
    _save_storyboard_for_api(sb_path, shots, req.episode, req.append)

    # 同步数据库
    try:
        from infra.database.pool import get_pool
        from infra.database.shots import upsert as db_upsert_shot
        pool = get_pool()
        for shot in shots:
            sid = shot.get("shot_id", "")
            if sid:
                db_upsert_shot(pool, req.episode, sid, shot)
    except Exception as e:
        logger.debug(f"数据库同步跳过: {e}")

    total_sec = sum(int(s.get("duration", 4)) for s in shots)
    return {
        "status": "ok",
        "shots": shots,
        "count": len(shots),
        "total_duration": total_sec,
    }


@router.post("/llm/characters")
def llm_generate_characters(req: CharacterGenRequest):
    """AI 生成角色配置"""
    llm = _get_llm_for_api()
    from engines.llm_generator import generate_characters

    chars = generate_characters(llm, req.descriptions)
    if not chars:
        raise HTTPException(500, "LLM 未能生成有效角色")

    # 保存
    proj_dir = _active_project_dir()
    char_dir = proj_dir / "config" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)

    import yaml
    saved = []
    for char in chars:
        cid = char.get("id", "unknown")
        path = char_dir / f"{cid}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump({"character": char}, f, allow_unicode=True, default_flow_style=False)
        # 同步数据库
        try:
            from infra.database.characters import upsert as db_up
            from infra.database.pool import get_pool
            db_up(get_pool(), cid, char)
        except Exception:
            pass
        saved.append(char)

    return {"status": "ok", "characters": saved, "count": len(saved)}


@router.post("/llm/scenes")
def llm_generate_scenes(req: SceneGenRequest):
    """AI 生成场景配置"""
    llm = _get_llm_for_api()
    from engines.llm_generator import generate_scenes

    scene_list = generate_scenes(llm, req.descriptions)
    if not scene_list:
        raise HTTPException(500, "LLM 未能生成有效场景")

    proj_dir = _active_project_dir()
    scene_dir = proj_dir / "config" / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)

    import yaml
    saved = []
    for scene in scene_list:
        sid = scene.get("id", "unknown")
        path = scene_dir / f"{sid}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump({"scene": scene}, f, allow_unicode=True, default_flow_style=False)
        try:
            from infra.database.scenes import upsert as db_up
            from infra.database.pool import get_pool
            db_up(get_pool(), sid, scene)
        except Exception:
            pass
        saved.append(scene)

    return {"status": "ok", "scenes": saved, "count": len(saved)}


def _save_storyboard_for_api(path: Path, shots: list[dict], episode: int, append: bool):
    """保存分镜到 CSV（API 用）"""
    fieldnames = ["episode", "shot_id", "scene", "characters", "action", "dialogue",
                  "camera", "shot_type", "duration", "outfit", "emotion",
                  "action_en", "dialogue_en"]
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if append and path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if int(row.get("episode", 0)) != episode:
                    existing.append(row)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing + shots)


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
    return get_episode_status(str(_active_project_dir()), episode)


# ══════════════════════════════════════════════════════════
# 镜头资源查询 + 文件预览（带路径遍历防护）
# ══════════════════════════════════════════════════════════

@router.get("/shots/{episode}/{shot_id}/resources")
def get_shot_resources(episode: int, shot_id: str):
    """查询镜头已生成的资源"""
    if episode < 1:
        raise HTTPException(400, "episode 必须 >= 1")
    if not re.match(r"^[a-zA-Z0-9_-]+$", shot_id):
        raise HTTPException(400, "无效的 shot_id")

    out_dir = _safe_path(_active_project_dir(), "output", f"e{episode:02d}", f"s{shot_id}")
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

    if episode < 1:
        raise HTTPException(400, "episode 必须 >= 1")
    if not re.match(r"^[a-zA-Z0-9_-]+$", shot_id):
        raise HTTPException(400, "无效的 shot_id")
    # 文件名只允许字母数字下划线连字符点号
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", filename):
        raise HTTPException(400, "无效的文件名")

    file_path = _safe_path(_active_project_dir(), "output", f"e{episode:02d}", f"s{shot_id}", filename)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    ext = file_path.suffix.lower()
    media_types = {
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))
