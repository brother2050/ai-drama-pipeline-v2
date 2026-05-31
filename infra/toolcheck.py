"""工具可用性检测 — 独立模块，供 pipeline / web 共用

从 web.routers.api 抽取，消除 pipeline → web 循环依赖。
"""
from __future__ import annotations

import logging
import os
import shutil
import time

from infra.network import port_ok as _port_ok

logger = logging.getLogger(__name__)

# 工具状态缓存（避免短时间内重复检测外部服务）
_tool_cache: dict[str, tuple[float, dict]] = {}
_TOOL_CACHE_TTL = 10  # 秒


def _url_ok(url: str, path: str = "/", headers: dict | None = None) -> bool:
    """检测 URL 是否可达（httpx 优先，urllib 回退）"""
    try:
        import httpx
        from infra.retry import retry
        def _check():
            r = httpx.get(f"{url}{path}", headers=headers, timeout=3)
            return r.status_code in (200, 401, 403)
        return retry(_check, max_retries=2, base_delay=0.5)
    except ImportError:
        pass
    except Exception:
        return False
    # httpx 不可用时用 urllib 回退
    try:
        import urllib.request
        req = urllib.request.Request(f"{url}{path}")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 401, 403)
    except Exception:
        return False


def check_tool(name: str, cfg: dict) -> dict:
    """检测单个工具的可用性（带 TTL 缓存）

    Args:
        name: 工具名 (tts / comfyui / lipsync / llm / music / ffmpeg / redis / celery)
        cfg: 项目配置 dict

    Returns:
        {"available": bool, "backend": str, "type": str, "reason": str, ...}
    """
    now = time.time()
    if name in _tool_cache:
        ts, result = _tool_cache[name]
        if now - ts < _TOOL_CACHE_TTL:
            return result
    result = _check_tool_inner(name, cfg)
    _tool_cache[name] = (now, result)
    return result


def _check_tool_inner(name: str, cfg: dict) -> dict:
    if name == "tts":
        backend = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
        if "mimo" in backend:
            # 检查配置文件或环境变量中的 API Key
            backend_key = backend.replace("-", "_")
            cfg_key = cfg.get("models", {}).get(backend_key, {}).get("api_key", "")
            ok = bool(cfg_key or os.environ.get("MIMO_API_KEY"))
            return {"available": ok, "backend": backend, "type": "cloud",
                    "reason": "" if ok else "MIMO_API_KEY 未配置（设置页或环境变量）"}
        else:
            api_url = cfg.get("models", {}).get(backend.replace("-", "_"), {}).get("api_url", "")
            ok = _url_ok(api_url) if api_url else False
            return {"available": ok, "backend": backend, "type": "api",
                    "url": api_url, "reason": "" if ok else f"{backend} 服务不可达"}

    elif name == "comfyui":
        comfyui_cfg = cfg.get("comfyui", {})
        url = comfyui_cfg.get("url", "http://127.0.0.1:8188")
        api_key = comfyui_cfg.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        ok = _url_ok(url, "/system_stats", headers=headers)
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

    elif name == "seko":
        seko_cfg = cfg.get("seko", {})
        api_key = seko_cfg.get("api_key") or os.environ.get("SEKO_API_KEY", "")
        ok = bool(api_key)
        return {"available": ok, "backend": "seko", "type": "cloud",
                "reason": "" if ok else "SEKO_API_KEY 未配置"}

    elif name == "training":
        training_cfg = cfg.get("training", {})
        api_url = training_cfg.get("api_url", "")
        if not api_url:
            return {"available": False, "backend": "ai-toolkit", "type": "gpu",
                    "reason": "训练服务地址未配置"}
        ok = _url_ok(api_url, "/api/gpu")
        return {"available": ok, "backend": "ai-toolkit", "type": "gpu",
                "url": api_url, "reason": "" if ok else f"AI Toolkit 服务不可达 ({api_url})"}

    elif name == "ip_adapter":
        # IP-Adapter 可用性 = ComfyUI 可用 + 模型文件存在于 ComfyUI 服务器
        ip_cfg = cfg.get("ip_adapter", {})
        if not ip_cfg.get("enabled", True):
            return {"available": False, "backend": "ip-adapter-plus", "type": "gpu",
                    "reason": "IP-Adapter 未启用"}
        # 检查 ComfyUI
        comfyui_cfg = cfg.get("comfyui", {})
        url = comfyui_cfg.get("url", "http://127.0.0.1:8188")
        api_key = comfyui_cfg.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        comfyui_ok = _url_ok(url, "/system_stats", headers=headers)
        if not comfyui_ok:
            return {"available": False, "backend": "ip-adapter-plus", "type": "gpu",
                    "reason": "ComfyUI 不可达"}
        # 模型文件检查通过配置告知（ComfyUI 服务器上模型文件无法直接 HTTP 检测）
        model = ip_cfg.get("model", "ip-adapter-plus-face_sd15.safetensors")
        return {"available": True, "backend": "ip-adapter-plus", "type": "gpu",
                "model": model, "reason": f"IP-Adapter Plus ({model})"}

    elif name == "pulid_flux":
        pulid_cfg = cfg.get("pulid_flux", {})
        if not pulid_cfg.get("enabled", True):
            return {"available": False, "backend": "pulid-flux", "type": "gpu",
                    "reason": "PuLID-Flux 未启用"}
        # 检查 ComfyUI
        comfyui_cfg = cfg.get("comfyui", {})
        url = comfyui_cfg.get("url", "http://127.0.0.1:8188")
        api_key = comfyui_cfg.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        comfyui_ok = _url_ok(url, "/system_stats", headers=headers)
        if not comfyui_ok:
            return {"available": False, "backend": "pulid-flux", "type": "gpu",
                    "reason": "ComfyUI 不可达"}
        model = pulid_cfg.get("model", "pulid_flux_v0.9.0.safetensors")
        return {"available": True, "backend": "pulid-flux", "type": "gpu",
                "model": model, "reason": f"PuLID-Flux ({model})"}

    return {"available": False, "backend": "unknown", "type": "unknown", "reason": "未知工具"}
