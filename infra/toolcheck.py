"""工具可用性检测 — 注册表驱动，零硬编码

从 models_registry.yaml 读取每个后端/服务的 health_check 配置，
通用执行器根据 type 字段执行对应检测逻辑。

新增工具只需在 YAML 中声明 health_check，不改代码。
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
        logger.debug(f"{type(e).__name__}: {e}")
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


def _get_cfg_value(cfg: dict, dot_path: str) -> str:
    """从配置 dict 中按 dot path 读取值

    例: _get_cfg_value(cfg, 'models.gpt_sovits.api_url') → cfg['models']['gpt_sovits']['api_url']
    """
    val = cfg
    for key in dot_path.split("."):
        if isinstance(val, dict):
            val = val.get(key)
        else:
            return ""
        if val is None:
            return ""
    return str(val) if val is not None else ""


def _resolve_auth(cfg: dict, api_key_from: str) -> dict | None:
    """从配置中解析认证 headers"""
    if not api_key_from:
        return None
    api_key = _get_cfg_value(cfg, api_key_from)
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return None


def check_tool(name: str, cfg: dict) -> dict:
    """检测单个工具的可用性（注册表驱动，带 TTL 缓存）

    Args:
        name: 工具名。支持两种格式：
            - 后端名: tts / comfyui / lipsync / llm / music / ffmpeg / redis / celery / seko / training
            - 复合名: ip_adapter / pulid_flux（自动映射到一致性方案或服务）
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
    """内部检测逻辑（注册表驱动）"""
    registry = _get_registry()

    # 1. 一致性方案（从注册表读取，不硬编码）
    consistency_map = registry.get_consistency_check_map()
    if name in consistency_map:
        return _check_consistency(name, cfg, registry, consistency_map[name])

    # 2. 辅助服务（从注册表 services 段查询）
    hc = registry.get_service_health_check(name)
    if hc:
        meta = registry.get_service_meta(name) or {}
        return _execute_health_check(name, hc, cfg,
                                     backend=meta.get("backend", name),
                                     type=meta.get("type", "unknown"))

    # 3. 服务类型名（如 "tts"、"llm"）→ 查默认后端
    service_types = registry.get_registered_service_types()
    if name in service_types:
        return _check_service_type_backend(name, cfg, registry)

    # 4. 后端名（如 "mimo-voicedesign"）→ 遍历所有服务类型匹配
    for service_type in service_types:
        cfg_key = registry.get_service_cfg_key(service_type)
        if service_type == "llm":
            backend_name = _get_cfg_value(cfg, "llm.backend") or registry.get_defaults().get(cfg_key, "")
        else:
            backend_name = _get_cfg_value(cfg, f"models.{cfg_key}") or registry.get_defaults().get(cfg_key, "")
        if backend_name == name:
            hc = registry.get_health_check(service_type, backend_name)
            if hc:
                return _execute_health_check(
                    name, hc, cfg,
                    backend=backend_name, service_type=service_type)

    return {"available": False, "backend": "unknown", "type": "unknown",
            "reason": f"未注册的工具: {name}"}


def _execute_health_check(name: str, hc: dict, cfg: dict,
                          backend: str = "", service_type: str = "",
                          type: str = "") -> dict:
    """通用健康检查执行器

    根据 hc.type 字段分发到对应的检测逻辑。
    """
    check_type = hc.get("type", "")
    result_backend = backend or name
    result_type = type or "unknown"

    if check_type == "api_key_env":
        env = hc.get("env", "")
        # 也检查配置文件中的值
        config_key = hc.get("config_key", "")
        cfg_val = _get_cfg_value(cfg, config_key) if config_key else ""
        ok = bool(os.environ.get(env) or cfg_val)
        reason = "" if ok else f"{env} 未配置（设置页或环境变量）"
        return _result(name, ok, result_backend, "cloud", reason)

    elif check_type == "http":
        url = _get_cfg_value(cfg, hc.get("config_key", ""))
        if not url:
            return _result(name, False, result_backend, result_type,
                           f"服务地址未配置 ({hc.get('config_key', '')})")
        headers = _resolve_auth(cfg, hc.get("api_key_from", ""))
        ok = _url_ok(url, hc.get("path", "/"), headers)
        reason = "" if ok else f"服务不可达 ({url})"
        return _result(name, ok, result_backend, result_type, reason)

    elif check_type == "ollama_tags":
        url = _get_cfg_value(cfg, hc.get("config_key", ""))
        if not url:
            return _result(name, False, result_backend, "cloud", "Ollama 地址未配置")
        ok = _url_ok(url, "/api/tags")
        reason = "" if ok else f"Ollama 不可达 ({url})"
        return _result(name, ok, result_backend, "cloud", reason)

    elif check_type == "openai_models":
        url = _get_cfg_value(cfg, hc.get("config_key", ""))
        if not url:
            return _result(name, False, result_backend, "cloud", "LLM 地址未配置")
        # 检查 enabled 状态（兼容 bool / str / None）
        llm_enabled = _get_cfg_value(cfg, "llm.enabled")
        if llm_enabled and str(llm_enabled).lower() in ("false", "0"):
            service_ok = _url_ok(url.rstrip("/") + "/v1/models",
                                headers=_resolve_auth(cfg, hc.get("api_key_from", "")))
            if service_ok:
                return _result(name, False, result_backend, "cloud",
                               "服务已就绪，但未启用（请在设置中开启）")
            return _result(name, False, result_backend, "cloud", "LLM 未启用")
        # 正常检测（确保 URL 以 /v1 结尾，避免重复拼接）
        check_url = url.rstrip("/")
        if not check_url.endswith("/v1"):
            check_url += "/v1"
        headers = _resolve_auth(cfg, hc.get("api_key_from", ""))
        ok = _url_ok(check_url, "/models", headers=headers)
        reason = "" if ok else f"LLM 服务不可达 ({url})"
        return _result(name, ok, result_backend, "cloud", reason)

    elif check_type == "command":
        cmd = hc.get("command", "")
        ok = bool(shutil.which(cmd))
        reason = "" if ok else f"{cmd} 未安装"
        return _result(name, ok, result_backend, "local", reason)

    elif check_type == "port":
        port = hc.get("port", 0)
        ok = _port_ok(port)
        reason = "" if ok else f"端口 {port} 未监听"
        return _result(name, ok, result_backend, "infra", reason)

    elif check_type == "celery_active":
        if not _port_ok(6379):
            return _result(name, False, result_backend, "infra",
                           "Redis 未运行（Celery 依赖 Redis）")
        try:
            from pipeline.celery_app import app
            insp = app.control.inspect(timeout=2)
            ok = bool(insp.active())
            reason = "" if ok else "Celery Worker 未启动"
            return _result(name, ok, result_backend, "infra", reason)
        except Exception:
            return _result(name, False, result_backend, "infra", "Celery 连接失败")

    return _result(name, False, result_backend, "unknown", f"未知检查类型: {check_type}")


def _check_consistency(name: str, cfg: dict, registry, method: dict) -> dict:
    """检测一致性方案的可用性（从注册表读取配置，不硬编码）"""
    config_key = method.get("config_key", "")
    if config_key:
        # 检查配置中是否显式禁用
        method_cfg = cfg.get(config_key, {})
        if isinstance(method_cfg, dict) and method_cfg.get("enabled") == False:
            return _result(name, False, name, "gpu", f"{name} 已禁用")

    # 检查 ComfyUI 是否可达（从注册表读取 URL，不硬编码）
    comfyui_meta = registry.get_service_meta("comfyui") or {}
    comfyui_hc = comfyui_meta.get("health_check", {})
    comfyui_url = _get_cfg_value(cfg, comfyui_hc.get("config_key", "comfyui.url")) or "http://127.0.0.1:8188"
    comfyui_key_from = comfyui_hc.get("api_key_from", "comfyui.api_key")
    headers = _resolve_auth(cfg, comfyui_key_from)
    comfyui_ok = _url_ok(comfyui_url, "/system_stats", headers=headers)
    if not comfyui_ok:
        return _result(name, False, name, "gpu", "ComfyUI 不可达")

    # 获取模型名
    model_name = ""
    if config_key:
        model_cfg = cfg.get(config_key, {})
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("model", "")
    return _result(name, True, name, "gpu",
                   f"{name} ({model_name})" if model_name else f"{name}")


def _check_service_type_backend(service_type: str, cfg: dict, registry) -> dict:
    """检测指定服务类型的当前后端

    Args:
        service_type: tts / lipsync / llm / music / image / video
        cfg: 项目配置
        registry: ModelRegistry 实例
    """
    cfg_key = registry.get_service_cfg_key(service_type)
    default_backend = registry.get_defaults().get(cfg_key, "")

    # LLM 的配置路径特殊：llm.backend 而非 models.llm_backend
    if service_type == "llm":
        backend_name = _get_cfg_value(cfg, "llm.backend") or default_backend
    else:
        backend_name = _get_cfg_value(cfg, f"models.{cfg_key}") or default_backend

    if not backend_name:
        return _result(service_type, False, service_type, "unknown",
                       f"未配置 {cfg_key}")

    hc = registry.get_health_check(service_type, backend_name)
    if not hc:
        return _result(service_type, False, backend_name, "unknown",
                       f"后端 '{backend_name}' 未声明 health_check")

    return _execute_health_check(
        service_type, hc, cfg,
        backend=backend_name, service_type=service_type)


def _result(name: str, available: bool, backend: str, type: str, reason: str) -> dict:
    return {"available": available, "backend": backend, "type": type, "reason": reason}


_registry_instance = None


def _get_registry():
    """获取 ModelRegistry 单例（使用统一的配置路径解析）"""
    global _registry_instance
    if _registry_instance is None:
        from flow.model_registry import ModelRegistry
        from infra.config import resolve_project_config
        try:
            config_path = resolve_project_config()
        except FileNotFoundError:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(root, "config", "project.yaml")
        _registry_instance = ModelRegistry(config_path)
    return _registry_instance
