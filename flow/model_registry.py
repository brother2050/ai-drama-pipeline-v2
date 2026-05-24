"""模型注册表 — 配置驱动的后端管理

从 config/models_registry.yaml 加载所有后端定义。
新增模型只需改 YAML，不改代码。
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

__all__ = ["ModelRegistry"]


def _builtin_defaults() -> dict:
    return {
        "image_backends": {
            "sd15": {"workflow": "01_first_frame_sd15.json", "is_flux": False,
                     "default_params": {"width": 512, "height": 512, "steps": 20, "cfg_scale": 7.5}},
            "flux": {"workflow": "01_first_frame_flux.json", "is_flux": True,
                     "default_params": {"width": 1024, "height": 576, "steps": 28, "cfg_scale": 3.5}},
        },
        "video_backends": {
            "animatediff": {"workflow": "02_img2video.json", "sampler_node": "KSampler",
                           "default_params": {"frames": 8, "fps": 8, "steps": 15, "denoise": 0.5}},
            "cogvideox": {"workflow": "03_img2video_cogvideo.json", "sampler_node": "CogVideoXSampler",
                         "default_params": {"frames": 16, "fps": 12, "steps": 20, "denoise": 0.55}},
        },
    }


class ModelRegistry:
    """配置驱动的模型注册表"""

    def __init__(self, config_path: str):
        config_dir = Path(config_path).resolve().parent
        registry_path = config_dir / "models_registry.yaml"
        self._data = self._load(str(registry_path))

    @staticmethod
    def _load(path: str) -> dict:
        if not os.path.exists(path):
            logger.debug(f"模型注册表不存在: {path}，使用内置默认值")
            return _builtin_defaults()
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def valid_image_backends(self) -> set[str]:
        return set(self._data.get("image_backends", {}).keys())

    def valid_video_backends(self) -> set[str]:
        return set(self._data.get("video_backends", {}).keys())

    def get_image_workflow(self, backend: str) -> str:
        return self._data.get("image_backends", {}).get(backend, {}).get("workflow", "")

    def get_video_workflow(self, backend: str) -> str:
        return self._data.get("video_backends", {}).get(backend, {}).get("workflow", "")

    def get_image_defaults(self, backend: str) -> dict:
        return dict(self._data.get("image_backends", {}).get(backend, {}).get("default_params", {}))

    def get_video_defaults(self, backend: str) -> dict:
        return dict(self._data.get("video_backends", {}).get(backend, {}).get("default_params", {}))

    def is_flux_backend(self, backend: str) -> bool:
        return bool(self._data.get("image_backends", {}).get(backend, {}).get("is_flux", False))

    def get_sampler_node(self, backend: str) -> str:
        # 检查 image_backends 和 video_backends 两个字典
        result = self._data.get("image_backends", {}).get(backend, {}).get("sampler_node")
        if result:
            return result
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    def get_video_sampler_node(self, backend: str) -> str:
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    def get_gpu_profile(self, key: str) -> dict:
        profiles = self._data.get("gpu_profiles", {})
        return dict(profiles.get(key, profiles.get("t4", {})))

    def get_all_gpu_profiles(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._data.get("gpu_profiles", {}).items()}

    def register_image_backend(self, name: str, workflow: str, params: dict, **kw):
        self._data.setdefault("image_backends", {})[name] = {
            "workflow": workflow, "default_params": params, **kw}

    def register_video_backend(self, name: str, workflow: str, params: dict, **kw):
        self._data.setdefault("video_backends", {})[name] = {
            "workflow": workflow, "default_params": params, **kw}

    def reload(self, config_path: str | None = None):
        if config_path:
            self._data = self._load(str(Path(config_path).resolve().parent / "models_registry.yaml"))
