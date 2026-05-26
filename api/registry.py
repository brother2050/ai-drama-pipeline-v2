"""服务注册表 — 后端自注册 + DI 容器

核心设计:
- BackendMeta: 后端元数据（注册时使用）
- ServiceRegistry: 注册表（单例）
- Container: DI 容器（按需创建 + 缓存 + 热重载）
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["BackendMeta", "ServiceRegistry", "Container", "registry", "container"]


@dataclass
class BackendMeta:
    """后端元数据"""
    name: str
    service_type: str  # tts / lipsync / image / video / music / llm
    factory: Callable[..., Any]
    requires_api_key: bool = False
    api_key_env: str = ""
    description: str = ""
    priority: int = 100
    tags: list[str] = field(default_factory=list)


class ServiceRegistry:
    """服务注册表"""

    def __init__(self):
        self._backends: dict[str, BackendMeta] = {}

    def register(self, meta: BackendMeta) -> None:
        key = f"{meta.service_type}:{meta.name}"
        self._backends[key] = meta

    def get(self, service_type: str, name: str) -> BackendMeta | None:
        return self._backends.get(f"{service_type}:{name}")

    def list_by_type(self, service_type: str) -> list[str]:
        candidates = [m for m in self._backends.values() if m.service_type == service_type]
        candidates.sort(key=lambda m: m.priority)
        return [m.name for m in candidates]

    def create(self, service_type: str, name: str, config: dict) -> Any:
        meta = self._backends.get(f"{service_type}:{name}")
        if not meta:
            available = self.list_by_type(service_type)
            raise ValueError(f"未注册的 {service_type} 后端: '{name}'，可用: {available}")
        return meta.factory(config)

    def auto_select(self, service_type: str, config: dict) -> str:
        """根据环境自动选择最佳后端"""
        models = config.get("models", {})
        candidates = sorted(
            [m for m in self._backends.values() if m.service_type == service_type],
            key=lambda m: m.priority)
        for meta in candidates:
            if meta.requires_api_key:
                key = os.environ.get(meta.api_key_env, "")
                if not key:
                    continue
            return meta.name
        raise ValueError(f"没有可用的 {service_type} 后端")


class Container:
    """DI 容器 — 按需创建 + 缓存 + 热重载"""

    _TYPE_KEY = {
        "tts": "tts_backend", "lipsync": "lip_sync_backend",
        "image": "image_backend", "video": "video_backend",
        "music": "music_backend", "llm": "llm_backend",
        "training": "training_backend",
    }

    def __init__(self, config: dict):
        self._config = config
        self._instances: dict[str, Any] = {}
        self._snapshots: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, service_type: str, name: str | None = None) -> Any:
        if name is None:
            name = self._resolve(service_type)
        key = f"{service_type}:{name}"
        with self._lock:
            if key in self._instances:
                return self._instances[key]
            cfg = self._backend_config(service_type, name)
            inst = registry.create(service_type, name, cfg)
            self._instances[key] = inst
            self._snapshots[key] = cfg
            return inst

    def _resolve(self, service_type: str) -> str:
        # 1. 优先从 models 段读取（如 tts_backend, image_backend）
        models = self._config.get("models", {})
        cfg_key = self._TYPE_KEY.get(service_type, f"{service_type}_backend")
        name = models.get(cfg_key)
        if name:
            # 配置值可能是工作流模板名（如 sd15/flux），而非 API 后端名
            # 检查是否为已注册的 API 后端，不是则回退到自动选择
            if registry.get(service_type, name):
                return name
            logger.debug(
                f"models.{cfg_key}='{name}' 不是已注册的 {service_type} API 后端，"
                f"回退到自动选择")
        # 2. 从顶层 service_type 段读取（如 llm.backend, training.backend）
        svc_cfg = self._config.get(service_type, {})
        if isinstance(svc_cfg, dict) and svc_cfg.get("backend"):
            return svc_cfg["backend"]
        # 3. 自动选择
        return registry.auto_select(service_type, self._config)

    def _backend_config(self, service_type: str, name: str) -> dict:
        models = self._config.get("models", {})
        key = name.replace("-", "_")
        cfg = {
            **models.get(key, {}),
            "timeouts": self._config.get("timeouts", {}),
            "project_dir": self._config.get("_project_dir", ""),
        }
        # 也从顶层 service_type 段读取（如 training, llm 等）
        service_cfg = self._config.get(service_type, {})
        if isinstance(service_cfg, dict):
            cfg.update(service_cfg)
        # image/video 后端自动继承 comfyui 顶层配置（url / timeout / api_key）
        if service_type in ("image", "video"):
            comfyui_cfg = self._config.get("comfyui", {})
            if isinstance(comfyui_cfg, dict):
                # 不覆盖已有的显式配置
                for field in ("url", "api_key"):
                    if field not in cfg or not cfg[field]:
                        cfg[field] = comfyui_cfg.get(field, "")
                # timeout 映射到 timeouts.comfyui
                if "timeouts" not in cfg:
                    cfg["timeouts"] = {}
                if "comfyui" not in cfg["timeouts"] or not cfg["timeouts"]["comfyui"]:
                    cfg["timeouts"]["comfyui"] = comfyui_cfg.get("timeout", 300)
                # video 后端需要 comfyui_url
                if service_type == "video" and "comfyui_url" not in cfg:
                    cfg["comfyui_url"] = comfyui_cfg.get("url", "http://127.0.0.1:8188")
        return cfg

    def reload(self, new_config: dict) -> list[str]:
        changed = []
        with self._lock:
            self._config = new_config
            for key, inst in list(self._instances.items()):
                stype, bname = key.split(":", 1)
                old = self._snapshots.get(key, {})
                new = self._backend_config(stype, bname)
                if old != new:
                    if hasattr(inst, "shutdown"):
                        inst.shutdown()
                    self._instances[key] = registry.create(stype, bname, new)
                    self._snapshots[key] = new
                    changed.append(key)
        return changed

    def shutdown_all(self):
        with self._lock:
            for inst in self._instances.values():
                if hasattr(inst, "shutdown"):
                    try:
                        inst.shutdown()
                    except Exception:
                        pass
            self._instances.clear()
            self._snapshots.clear()


# 全局单例
registry = ServiceRegistry()
container: Container | None = None
