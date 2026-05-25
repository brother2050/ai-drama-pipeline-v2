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
        try:
            with open(abspath, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error(f"配置文件 YAML 格式错误: {abspath}: {e}")
            data = {}
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

    # 默认配置（project.name 不设默认值，由 REQUIRED_FIELDS 强制要求）
    DEFAULTS: dict[str, Any] = {
        "project": {"episodes": 1, "fps": 24, "resolution": [1280, 720],
                     "style": "cinematic", "genre": "urban"},
        "comfyui": {"url": "http://127.0.0.1:8188", "timeout": 300, "api_key": ""},
        "models": {"tts_backend": "mimo-voicedesign", "lip_sync_backend": "musetalk",
                   "music_backend": "template", "image_backend": "sd15", "video_backend": "animatediff"},
        "server": {"port": 8888, "host": "0.0.0.0", "cors_origin": "*"},
        "timeouts": {"comfyui": 300, "tts": 60, "lipsync": 120, "llm": 300, "music": 120},
    }

    # 必填字段校验规则
    REQUIRED_FIELDS: list[tuple[str, str]] = [
        ("project.name", "项目名称"),
    ]

    # 合法值范围
    VALID_RANGES: dict[str, tuple[int, int]] = {
        "project.fps": (1, 120),
        "server.port": (1, 65535),
        "comfyui.timeout": (1, 3600),
        "post_production.transition_duration": (0, 10),
        "post_production.bgm_volume": (0, 1),
        "timeouts.comfyui": (1, 7200),
        "timeouts.tts": (1, 600),
        "timeouts.lipsync": (1, 600),
        "timeouts.llm": (1, 3600),
        "timeouts.music": (1, 600),
    }

    def __init__(self, path: str | None = None):
        self._path = path or self._find_config()
        self._data = self._merge(self._path)
        self._project_dir = str(Path(self._path).resolve().parent.parent) if self._path else os.getcwd()
        # 注入 project_dir 供后端使用（Container._backend_config 依赖此键）
        self._data["_project_dir"] = self._project_dir
        self._warnings: list[str] = []
        self._validate()

    @staticmethod
    def _find_config() -> str:
        """查找配置文件（活动项目优先，回退到 projects/default/）"""
        root = Path(__file__).resolve().parent.parent
        # 1. 检查 .active 指向的项目
        active_file = root / "projects" / ".active"
        if active_file.exists():
            d = active_file.read_text().strip()
            cfg = Path(d) / "config" / "project.yaml"
            if cfg.exists():
                return str(cfg)
        # 2. 回退到默认项目
        cfg = root / "projects" / "default" / "config" / "project.yaml"
        if cfg.exists():
            return str(cfg)
        # 3. 兼容旧结构（根目录 config/）
        cfg = root / "config" / "project.yaml"
        if cfg.exists():
            return str(cfg)
        raise FileNotFoundError("未找到 config/project.yaml，请先初始化默认项目")

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
        self._data["_project_dir"] = self._project_dir
        self._warnings = []
        self._validate()

    def _validate(self) -> None:
        """校验配置合法性（不阻断，仅记录警告）"""
        # 必填字段
        for field, desc in self.REQUIRED_FIELDS:
            val = self.get(field)
            if val is None or val == "":
                self._warnings.append(f"缺少必填配置: {desc} ({field})")

        # 数值范围
        for field, (lo, hi) in self.VALID_RANGES.items():
            val = self.get(field)
            if val is not None:
                try:
                    v = int(val)
                    if v < lo or v > hi:
                        self._warnings.append(
                            f"配置 {field}={v} 超出范围 [{lo}, {hi}]"
                        )
                except (ValueError, TypeError):
                    self._warnings.append(f"配置 {field} 不是有效数值: {val}")

        # 分辨率格式
        res = self.get("project.resolution")
        if res is not None:
            if not isinstance(res, list) or len(res) != 2:
                self._warnings.append("project.resolution 应为 [width, height] 格式")
            elif not all(isinstance(x, (int, float)) and x > 0 for x in res):
                self._warnings.append("project.resolution 的值必须为正数")

        if self._warnings:
            for w in self._warnings:
                logger.warning(f"⚠ 配置校验: {w}")

    @property
    def warnings(self) -> list[str]:
        """返回配置校验警告列表"""
        return list(self._warnings)

    def __repr__(self) -> str:
        return f"Config({self._path})"
