"""配置管理 — 单一数据源，线程安全，带缓存"""

from __future__ import annotations

import copy
import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env, override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)

__all__ = ["Config", "load_config", "save_config"]

_cache: dict[str, tuple[dict, float]] = {}
_lock = threading.Lock()


def load_config(path: str, *, force: bool = False) -> dict[str, Any]:
    """加载 YAML 配置（带 mtime 缓存）"""
    abspath = str(Path(path).resolve())
    if not os.path.isfile(abspath):
        logger.warning(f"Config not found: {abspath}")
        return {}

    if not force and abspath in _cache:
        data, mtime = _cache[abspath]
        if os.path.getmtime(abspath) == mtime:
            return copy.deepcopy(data)

    with _lock:
        if not force and abspath in _cache:
            data, mtime = _cache[abspath]
            if os.path.getmtime(abspath) == mtime:
                return copy.deepcopy(data)
        with open(abspath, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _cache[abspath] = (data, os.path.getmtime(abspath))
    return copy.deepcopy(data)


def save_config(path: str, data: dict[str, Any]) -> None:
    """保存 YAML 配置"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    abspath = str(Path(path).resolve())
    with _lock:
        _cache[abspath] = (data, os.path.getmtime(abspath))


class Config:
    """统一配置对象 — 聚合 project.yaml + .env + 默认值"""

    # 默认配置
    DEFAULTS: dict[str, Any] = {
        "project": {"name": "AI短剧", "episodes": 1, "fps": 24, "resolution": [1280, 720],
                     "style": "cinematic", "genre": "urban"},
        "comfyui": {"url": "http://127.0.0.1:8188", "timeout": 300, "api_key": ""},
        "models": {"tts_backend": "mimo-voicedesign", "lip_sync_backend": "musetalk",
                   "music_backend": "template", "image_backend": "sd15", "video_backend": "animatediff"},
        "server": {"port": 8888, "host": "0.0.0.0", "cors_origin": "*"},
        "timeouts": {"comfyui": 300, "tts": 60, "lipsync": 120, "llm": 300, "music": 120},
    }

    def __init__(self, path: str | None = None):
        self._path = path or self._find_config()
        self._data = self._merge(self._path)
        self._project_dir = str(Path(self._path).resolve().parent.parent) if self._path else os.getcwd()

    @staticmethod
    def _find_config() -> str:
        """查找配置文件"""
        candidates = [
            Path.cwd() / "config" / "project.yaml",
            Path(__file__).resolve().parent.parent / "config" / "project.yaml",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        raise FileNotFoundError("未找到 config/project.yaml，请在项目目录下运行或使用 -c 指定路径")

    def _merge(self, path: str) -> dict:
        """合并默认配置 + 文件配置"""
        merged = copy.deepcopy(self.DEFAULTS)
        if path and os.path.isfile(path):
            file_data = load_config(path)
            self._deep_merge(merged, file_data)
        return merged

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                Config._deep_merge(base[k], v)
            else:
                base[k] = v

    @property
    def data(self) -> dict:
        return self._data

    @property
    def project_dir(self) -> str:
        return self._project_dir

    @property
    def path(self) -> str:
        return self._path or ""

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持 dot notation: 'models.tts_backend'）"""
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    def reload(self) -> None:
        """重新加载配置"""
        self._data = self._merge(self._path)

    def __repr__(self) -> str:
        return f"Config({self._path})"
