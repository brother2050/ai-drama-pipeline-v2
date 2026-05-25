"""工具可用性检测 — 独立模块，供 pipeline / web 共用

从 web.routers.api 抽取，消除 pipeline → web 循环依赖。
"""
from __future__ import annotations

import logging
import os
import shutil
import socket

logger = logging.getLogger(__name__)


def _port_ok(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _url_ok(url: str, path: str = "/") -> bool:
    try:
        import httpx
        from infra.retry import retry
        return retry(lambda: httpx.get(f"{url}{path}", timeout=3).status_code == 200,
                     max_retries=2, base_delay=0.5)
    except Exception:
        return False


def check_tool(name: str, cfg: dict) -> dict:
    """检测单个工具的可用性

    Args:
        name: 工具名 (tts / comfyui / lipsync / llm / music / ffmpeg / redis / celery)
        cfg: 项目配置 dict

    Returns:
        {"available": bool, "backend": str, "type": str, "reason": str, ...}
    """
    if name == "tts":
        backend = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
        if "mimo" in backend:
            ok = bool(os.environ.get("MIMO_API_KEY"))
            return {"available": ok, "backend": backend, "type": "cloud",
                    "reason": "" if ok else "MIMO_API_KEY 未配置"}
        else:
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
            ok = bool(shutil.which("ffmpeg"))
            return {"available": ok, "backend": "template", "type": "local",
                    "reason": "" if ok else "ffmpeg 未安装"}
        else:
            api_url = cfg.get("models", {}).get(backend, {}).get("api_url", "")
            ok = _url_ok(api_url) if api_url else False
            return {"available": ok, "backend": backend, "type": "gpu",
                    "reason": "" if ok else f"{backend} 服务不可达"}

    elif name == "ffmpeg":
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
