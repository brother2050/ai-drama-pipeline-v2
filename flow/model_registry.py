"""模型注册表 — 配置驱动的后端管理

从 config/models_registry.yaml 加载所有后端定义。
新增模型只需改 YAML，不改代码。

设计原则：
- 所有后端元数据的唯一真相来源
- 零硬编码后端名
- 通用查询接口，按 service_type/name 访问
"""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

__all__ = ["ModelRegistry"]


# ── 内置兜底默认值（注册表文件不存在时使用） ──

def _builtin_defaults() -> dict:
    return {
        "defaults": {
            "tts_backend": "mimo-voicedesign",
            "lip_sync_backend": "musetalk",
            "music_backend": "template",
            "image_backend": "sd15",
            "video_backend": "animatediff",
        },
        "image_backends": {
            "sd15": {"workflow": "01_first_frame_sd15.json", "prompt_style": "tag",
                     "consistency_default": "ip_adapter",
                     "default_params": {"width": 512, "height": 512, "steps": 20, "cfg_scale": 7.5}},
            "flux": {"workflow": "01_first_frame_flux.json", "prompt_style": "natural",
                     "consistency_default": "pulid_flux",
                     "default_params": {"width": 1024, "height": 576, "steps": 28, "cfg_scale": 3.5}},
            "cosmos": {"workflow": "cosmos_predict2_2B_t2i.json", "prompt_style": "natural",
                       "consistency_default": "none",
                       "default_params": {"width": 1024, "height": 576, "steps": 35, "cfg_scale": 4}},
        },
        "video_backends": {
            "animatediff": {"workflow": "02_img2video.json", "sampler_node": "KSampler",
                           "frame_params": {"node_class": "ADE_StandardStaticContextOptions",
                                            "input_name": "context_length"},
                           "default_params": {"frames": 8, "fps": 8, "steps": 15, "denoise": 0.5}},
            "cogvideox": {"workflow": "03_img2video_cogvideo.json", "sampler_node": "CogVideoXSampler",
                         "frame_params": {"node_class": "EmptyLatentImage", "input_name": "batch_size"},
                         "default_params": {"width": 720, "height": 480, "frames": 16, "fps": 12,
                                            "steps": 20, "denoise": 0.55}},
            "cosmos-video": {"workflow": "04_img2video_cosmos.json", "sampler_node": "KSampler",
                            "frame_params": {"node_class": "CosmosPredict2ImageToVideoLatent",
                                             "input_name": "length"},
                            "default_params": {"width": 848, "height": 480, "frames": 93, "fps": 16,
                                               "steps": 35, "denoise": 1}},
        },
        "consistency_methods": {
            "ip_adapter": {"compatible_backends": ["sd15", "sdxl"], "config_key": "ip_adapter",
                           "inject_method": "_inject_ip_adapter_plus",
                           "required_comfyui_node": "IPAdapterAdvanced"},
            "pulid_flux": {"compatible_backends": ["flux"], "config_key": "pulid_flux",
                           "inject_method": "_inject_pulid_flux",
                           "required_comfyui_node": "PulidFluxModelLoader"},
            "none": {"compatible_backends": ["*"]},
        },
        "pipeline_steps": [
            {"name": "tts", "task": "pipeline.step.tts", "tool": "tts", "timeout": 120},
            {"name": "first_frame", "task": "pipeline.step.first_frame", "tool": "comfyui", "timeout": 300},
            {"name": "video", "task": "pipeline.step.video", "tool": "comfyui", "timeout": 600},
            {"name": "lipsync", "task": "pipeline.step.lipsync", "tool": "lipsync", "timeout": 300},
        ],
    }


class ModelRegistry:
    """配置驱动的模型注册表

    所有后端元数据的唯一查询入口。按 service_type + name 访问。
    """

    # 服务类型 → 注册表中的顶层 key
    _SECTION_MAP = {
        "tts": "tts_backends",
        "lipsync": "lipsync_backends",
        "llm": "llm_backends",
        "music": "music_backends",
        "image": "image_backends",
        "video": "video_backends",
    }

    def __init__(self, config_path: str):
        config_dir = Path(config_path).resolve().parent
        registry_path = config_dir / "models_registry.yaml"
        if not registry_path.exists():
            # 回退到根目录 config/（全局注册表）
            root = Path(__file__).resolve().parent.parent
            registry_path = root / "config" / "models_registry.yaml"
        self._data = self._load(str(registry_path))

    @staticmethod
    def _load(path: str) -> dict:
        if not os.path.exists(path):
            logger.debug(f"模型注册表不存在: {path}，使用内置默认值")
            return _builtin_defaults()
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning(f"模型注册表 YAML 格式错误: {e}，使用内置默认值")
            return _builtin_defaults()

        # 与内置默认值合并（确保缺失字段有兜底）
        defaults = _builtin_defaults()
        _deep_merge(defaults, data)
        return defaults

    # ══════════════════════════════════════════════════════════
    #  全局默认值
    # ══════════════════════════════════════════════════════════

    def get_defaults(self) -> dict[str, str]:
        """返回全局默认后端名映射 {'tts_backend': 'mimo-voicedesign', ...}"""
        return copy.deepcopy(self._data.get("defaults", {}))

    # ══════════════════════════════════════════════════════════
    #  通用后端查询
    # ══════════════════════════════════════════════════════════

    def get_backend(self, service_type: str, name: str) -> dict | None:
        """查询单个后端的完整元数据

        Args:
            service_type: tts / lipsync / llm / music / image / video
            name: 后端名（如 mimo-voicedesign, sd15, animatediff）

        Returns:
            后端元数据 dict，不存在返回 None（返回副本，修改不影响注册表）
        """
        section = self._SECTION_MAP.get(service_type)
        if not section:
            logger.warning(f"未知服务类型: {service_type}")
            return None
        backend = self._data.get(section, {}).get(name)
        return copy.deepcopy(backend) if backend is not None else None

    def get_backends(self, service_type: str) -> dict[str, dict]:
        """返回某服务类型的所有后端 {'name': {metadata}}（返回副本）"""
        section = self._SECTION_MAP.get(service_type)
        if not section:
            return {}
        return copy.deepcopy(self._data.get(section, {}))

    def list_backend_names(self, service_type: str) -> list[str]:
        """返回某服务类型的所有后端名列表（返回副本）"""
        section = self._SECTION_MAP.get(service_type)
        if not section:
            return []
        return list(self._data.get(section, {}).keys())

    # ══════════════════════════════════════════════════════════
    #  健康检查
    # ══════════════════════════════════════════════════════════

    def get_health_check(self, service_type: str, name: str) -> dict | None:
        """返回后端的健康检查配置

        Returns:
            {'type': 'http', 'path': '/', 'config_key': 'models.gpt_sovits.api_url'} 或 None（返回副本）
        """
        backend = self.get_backend(service_type, name)
        if backend:
            hc = backend.get("health_check")
            return copy.deepcopy(hc) if hc is not None else None
        return None

    def get_service_health_check(self, service_name: str) -> dict | None:
        """返回辅助服务的健康检查配置（从 services 段读取）

        Args:
            service_name: comfyui / redis / celery / ffmpeg / seko / training

        Returns:
            健康检查配置 dict 或 None（返回副本）
        """
        hc = self._data.get("services", {}).get(service_name, {}).get("health_check")
        return copy.deepcopy(hc) if hc is not None else None

    def get_all_health_checks(self) -> dict[str, dict]:
        """返回所有需要健康检查的项（后端 + 辅助服务）

        Returns:
            {'tts:mimo-voicedesign': {'type': 'api_key_env', ...},
             'comfyui': {'type': 'http', ...}, ...}
        """
        result = {}

        # 后端的健康检查
        for service_type, section in self._SECTION_MAP.items():
            for name, meta in self._data.get(section, {}).items():
                hc = meta.get("health_check")
                if hc:
                    result[f"{service_type}:{name}"] = hc

        # 辅助服务的健康检查
        for name, meta in self._data.get("services", {}).items():
            hc = meta.get("health_check")
            if hc:
                result[name] = hc

        return result

    # ══════════════════════════════════════════════════════════
    #  图像后端
    # ══════════════════════════════════════════════════════════

    def get_image_workflow(self, backend: str) -> str:
        """返回图像后端的工作流文件名"""
        return self._data.get("image_backends", {}).get(backend, {}).get("workflow", "")

    def get_image_defaults(self, backend: str) -> dict:
        """返回图像后端的默认生成参数（返回副本）"""
        return copy.deepcopy(self._data.get("image_backends", {}).get(backend, {}).get("default_params", {}))

    def get_prompt_style(self, image_backend: str) -> str:
        """返回图像后端的 prompt 风格 ('tag' / 'natural')

        - tag: 逗号分隔短语（SD1.5/SDXL，CLIP 编码器）
        - natural: 自然语言段落（Flux/Cosmos，T5 编码器）
        """
        return self._data.get("image_backends", {}).get(image_backend, {}).get("prompt_style", "tag")

    def get_consistency_default(self, image_backend: str) -> str:
        """返回图像后端的默认一致性方案

        Returns:
            'ip_adapter' / 'pulid_flux' / 'none'
        """
        return self._data.get("image_backends", {}).get(image_backend, {}).get("consistency_default", "none")

    # ══════════════════════════════════════════════════════════
    #  视频后端
    # ══════════════════════════════════════════════════════════

    def get_video_workflow(self, backend: str) -> str:
        """返回视频后端的工作流文件名"""
        return self._data.get("video_backends", {}).get(backend, {}).get("workflow", "")

    def get_video_defaults(self, backend: str) -> dict:
        """返回视频后端的默认生成参数（返回副本）"""
        return copy.deepcopy(self._data.get("video_backends", {}).get(backend, {}).get("default_params", {}))

    def get_frame_params(self, video_backend: str) -> dict | None:
        """返回视频后端的帧数注入规则

        Returns:
            {'node_class': 'ADE_StandardStaticContextOptions', 'input_name': 'context_length'}
            或 None（后端未声明帧数注入规则，返回副本）
        """
        fp = self._data.get("video_backends", {}).get(video_backend, {}).get("frame_params")
        return copy.deepcopy(fp) if fp is not None else None

    def get_sampler_node(self, backend: str) -> str:
        """返回后端的采样器节点类型名（image 或 video）"""
        result = self._data.get("image_backends", {}).get(backend, {}).get("sampler_node")
        if result:
            return result
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    def get_video_sampler_node(self, backend: str) -> str:
        """返回视频后端的采样器节点类型名"""
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    # ══════════════════════════════════════════════════════════
    #  一致性方案
    # ══════════════════════════════════════════════════════════

    def get_consistency_method(self, name: str) -> dict | None:
        """返回一致性方案的元数据

        Returns:
            {'compatible_backends': ['sd15', 'sdxl'], 'config_key': 'ip_adapter',
             'inject_method': '_inject_ip_adapter_plus'}
            或 None（返回副本）
        """
        method = self._data.get("consistency_methods", {}).get(name)
        return copy.deepcopy(method) if method is not None else None

    def get_compatible_consistency(self, image_backend: str) -> list[str]:
        """返回与某图像后端兼容的所有一致性方案名"""
        methods = self._data.get("consistency_methods", {})
        result = []
        for name, meta in methods.items():
            compat = meta.get("compatible_backends", [])
            if "*" in compat or image_backend.lower() in compat:
                result.append(name)
        return result

    # ══════════════════════════════════════════════════════════
    #  生产步骤编排
    # ══════════════════════════════════════════════════════════

    def get_pipeline_steps(self) -> list[dict]:
        """返回生产步骤编排列表

        Returns:
            [{'name': 'tts', 'task': 'pipeline.step.tts', 'tool': 'tts', 'timeout': 120}, ...]
            （返回副本）
        """
        return copy.deepcopy(self._data.get("pipeline_steps", []))

    # ══════════════════════════════════════════════════════════
    #  已有接口（向后兼容）
    # ══════════════════════════════════════════════════════════

    def valid_image_backends(self) -> set[str]:
        return set(self._data.get("image_backends", {}).keys())

    def valid_video_backends(self) -> set[str]:
        return set(self._data.get("video_backends", {}).keys())

    def valid_tts_backends(self) -> set[str]:
        return set(self._data.get("tts_backends", {}).keys())

    def valid_lipsync_backends(self) -> set[str]:
        return set(self._data.get("lipsync_backends", {}).keys())

    def valid_llm_backends(self) -> set[str]:
        return set(self._data.get("llm_backends", {}).keys())

    def valid_music_backends(self) -> set[str]:
        return set(self._data.get("music_backends", {}).keys())

    def get_tts_backends(self) -> dict:
        """获取所有 TTS 后端及其描述（向后兼容，返回副本）"""
        return copy.deepcopy(self._data.get("tts_backends", {}))

    def get_lipsync_backends(self) -> dict:
        return copy.deepcopy(self._data.get("lipsync_backends", {}))

    def get_llm_backends(self) -> dict:
        return copy.deepcopy(self._data.get("llm_backends", {}))

    def get_music_backends(self) -> dict:
        return copy.deepcopy(self._data.get("music_backends", {}))

    def register_image_backend(self, name: str, workflow: str, params: dict, **kw):
        self._data.setdefault("image_backends", {})[name] = {
            "workflow": workflow, "default_params": params, **kw}

    def register_video_backend(self, name: str, workflow: str, params: dict, **kw):
        self._data.setdefault("video_backends", {})[name] = {
            "workflow": workflow, "default_params": params, **kw}

    def reload(self, config_path: str | None = None):
        if config_path:
            self._data = self._load(str(Path(config_path).resolve().parent / "models_registry.yaml"))


def _deep_merge(base: dict, override: dict) -> None:
    """深度合并 override 到 base 中（就地修改 base）"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
