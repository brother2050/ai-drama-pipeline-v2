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


def _url_ok(url: str, path: str = "/", headers: dict | None = None) -> bool:
    try:
        import httpx
        from infra.retry import retry
        def _check():
            r = httpx.get(f"{url}{path}", headers=headers, timeout=3)
            return r.status_code in (200, 401, 403)  # 401/403 = 服务在线但认证问题
        return retry(_check, max_retries=2, base_delay=0.5)
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
        base_url = llm_cfg.get("base_url", "http://localhost:11434")
        backend = llm_cfg.get("backend", "ollama")
        enabled = llm_cfg.get("enabled")
        api_key = llm_cfg.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        # Ollama 用 /api/tags，OpenAI 兼容用 /v1/models
        if backend == "ollama":
            service_ok = _url_ok(base_url, "/api/tags")
        else:
            # SiliconFlow / OpenAI / Zhipu 等 OpenAI 兼容 API
            check_url = base_url.rstrip("/")
            if not check_url.endswith("/v1"):
                check_url = check_url + "/v1"
            service_ok = _url_ok(check_url, "/models", headers=headers)
        if not enabled:
            if service_ok:
                return {"available": False, "backend": backend, "type": "cloud",
                        "url": base_url, "reason": "服务已就绪，但未启用（请在设置中开启）"}
            return {"available": False, "backend": "disabled", "type": "cloud",
                    "reason": "LLM 未启用"}
        return {"available": service_ok, "backend": backend, "type": "cloud",
                "url": base_url, "reason": "" if service_ok else f"LLM 服务不可达 ({base_url})"}

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
