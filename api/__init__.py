"""API 后端层 — 懒加载注册

改为按需 import，避免启动时加载所有后端模块（含重依赖如 torch 等）。
后端模块在首次 Container.get() 时才被导入和注册。
"""
from __future__ import annotations

import importlib
import logging
import threading

logger = logging.getLogger(__name__)

# 后端模块注册表: (service_type, module_path, priority)
_BACKEND_MODULES = [
    ("tts", "api.backends.tts.mimo_voicedesign", 10),
    ("tts", "api.backends.tts.mimo_voiceclone", 20),
    ("tts", "api.backends.tts.gpt_sovits", 30),
    ("tts", "api.backends.tts.cosyvoice", 40),
    ("tts", "api.backends.tts.fish_speech", 50),
    ("lipsync", "api.backends.lipsync.musetalk", 10),
    ("lipsync", "api.backends.lipsync.wav2lip", 20),
    ("image", "api.backends.image.comfyui", 10),
    ("video", "api.backends.video.animatediff", 10),
    ("llm", "api.backends.llm.ollama", 10),
    ("music", "api.backends.music.template", 10),
    ("training", "api.backends.training.kohya_ss", 10),
    ("seko", "api.backends.seko", 10),
]

_loaded = False
_register_lock = threading.Lock()


def _ensure_registered():
    """懒加载: 首次调用时导入所有后端模块触发注册（线程安全）"""
    global _loaded
    if _loaded:
        return
    with _register_lock:
        if _loaded:
            return
        _loaded = True

        for service_type, module_path, _priority in _BACKEND_MODULES:
            try:
                importlib.import_module(module_path)
            except ImportError as e:
                logger.debug(f"跳过后端 {module_path}: {e}")
            except Exception as e:
                logger.warning(f"加载后端 {module_path} 失败: {e}")


def get_registry():
    """获取注册表（触发懒加载）"""
    _ensure_registered()
    from api.registry import registry
    return registry


def get_container(config: dict):
    """获取 DI 容器（触发懒加载）"""
    _ensure_registered()
    from api.registry import Container
    return Container(config)
