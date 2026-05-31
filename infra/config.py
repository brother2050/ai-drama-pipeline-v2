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

__all__ = ["Config", "ProjectPaths", "load_config", "save_config", "SYSTEM_CONFIG_PATH"]

# 系统全局配置路径（单一数据源，避免各处重复拼接）
_ROOT = Path(__file__).resolve().parent.parent
SYSTEM_CONFIG_PATH = str(_ROOT / "config" / "system.yaml")


class ProjectPaths:
    """统一路径管理 — 所有项目路径的单一数据源

    两个核心目录:
      - root: 项目根目录（如 projects/default/）
      - episode_dir(n): 某集的输出目录（如 projects/default/output/e01/）

    用法:
      paths = ProjectPaths("/path/to/projects/default")
      paths.characters_dir          # .../config/characters/
      paths.storyboard_csv          # .../storyboard/episodes.csv
      paths.character_yaml("guchen")# .../config/characters/guchen.yaml
      paths.episode_dir(1)          # .../output/e01/
      paths.shot_dir(1, "001")      # .../output/e01/s001/
      paths.shot_frame(1, "001")    # .../output/e01/s001/frame.png
      paths.episode_srt(1)          # .../output/e01/episode_01.srt
      paths.episode_final(1)        # .../output/e01/episode_01_final.mp4
    """

    def __init__(self, project_dir: str | Path):
        self._root = Path(project_dir).resolve()

    @property
    def root(self) -> Path:
        """项目根目录"""
        return self._root

    # ── 配置 ──────────────────────────────────────────

    @property
    def config_dir(self) -> Path:
        """项目配置目录"""
        return self._root / "config"

    @property
    def project_yaml(self) -> Path:
        """项目配置文件"""
        return self._root / "config" / "project.yaml"

    @property
    def characters_dir(self) -> Path:
        """角色配置目录"""
        return self._root / "config" / "characters"

    @property
    def scenes_dir(self) -> Path:
        """场景配置目录"""
        return self._root / "config" / "scenes"

    def character_yaml(self, char_id: str) -> Path:
        """角色配置文件"""
        return self._root / "config" / "characters" / f"{char_id}.yaml"

    def scene_yaml(self, scene_id: str) -> Path:
        """场景配置文件"""
        return self._root / "config" / "scenes" / f"{scene_id}.yaml"

    # ── 分镜 ──────────────────────────────────────────

    @property
    def storyboard_dir(self) -> Path:
        """分镜表目录"""
        return self._root / "storyboard"

    @property
    def storyboard_csv(self) -> Path:
        """分镜表 CSV"""
        return self._root / "storyboard" / "episodes.csv"

    # ── 资产 ──────────────────────────────────────────

    @property
    def assets_dir(self) -> Path:
        """资产根目录"""
        return self._root / "assets"

    @property
    def character_assets_dir(self) -> Path:
        """角色资产目录"""
        return self._root / "assets" / "characters"

    @property
    def scene_assets_dir(self) -> Path:
        """场景资产目录"""
        return self._root / "assets" / "scenes"

    @property
    def loras_dir(self) -> Path:
        """LoRA 模型目录"""
        return self._root / "assets" / "loras"

    def character_asset_dir(self, char_id: str) -> Path:
        """角色资产目录"""
        return self._root / "assets" / "characters" / char_id

    def character_lora_dir(self, char_id: str) -> Path:
        """角色 LoRA 子目录"""
        return self._root / "assets" / "characters" / char_id / "lora"

    def character_outfit_dir(self, char_id: str, outfit_key: str) -> Path:
        """角色服装资产目录"""
        return self._root / "assets" / "characters" / char_id / outfit_key

    def scene_asset_dir(self, scene_id: str) -> Path:
        """场景资产目录"""
        return self._root / "assets" / "scenes" / scene_id

    # ── 输出（集级） ──────────────────────────────────

    @property
    def output_dir(self) -> Path:
        """输出根目录"""
        return self._root / "output"

    def episode_dir(self, episode: int) -> Path:
        """某集的输出目录"""
        return self._root / "output" / f"e{episode:02d}"

    def episode_srt(self, episode: int) -> Path:
        """某集的 SRT 字幕文件"""
        return self._root / "output" / f"e{episode:02d}" / f"episode_{episode:02d}.srt"

    def episode_final(self, episode: int) -> Path:
        """某集的成片文件"""
        return self._root / "output" / f"e{episode:02d}" / f"episode_{episode:02d}_final.mp4"

    def shot_dir(self, episode: int, shot_id: str) -> Path:
        """镜头输出目录"""
        return self._root / "output" / f"e{episode:02d}" / f"s{shot_id}"

    def shot_audio(self, episode: int, shot_id: str) -> Path:
        """镜头音频"""
        return self.shot_dir(episode, shot_id) / "audio.wav"

    def shot_frame(self, episode: int, shot_id: str) -> Path:
        """镜头首帧"""
        return self.shot_dir(episode, shot_id) / "frame.png"

    def shot_video(self, episode: int, shot_id: str) -> Path:
        """镜头视频"""
        return self.shot_dir(episode, shot_id) / "video.mp4"

    def shot_synced(self, episode: int, shot_id: str) -> Path:
        """镜头口型同步视频"""
        return self.shot_dir(episode, shot_id) / "synced.mp4"

    # ── 工作流 ──────────────────────────────────────────

    @property
    def workflows_dir(self) -> Path:
        """工作流模板目录"""
        return self._root / "workflows"

    # ── 其他 ──────────────────────────────────────────

    @property
    def shared_assets_dir(self) -> Path:
        """全局共享资产目录（仓库根目录级别）"""
        return self._root.parent.parent / "shared_assets"

    @property
    def tts_preview_dir(self) -> Path:
        """TTS 预览目录"""
        return self._root / "output" / "tts_preview"

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return self._root / "logs"

    def bgm_file(self, tag: str = "") -> Path:
        """配乐文件路径（tag 用于区分不同用途，如时间戳）"""
        name = f"bgm_{tag}.wav" if tag else "bgm.wav"
        return self._root / "output" / name

    def config_entity_dir(self, entity_type: str) -> Path:
        """通用实体配置目录（characters / scenes）"""
        return self._root / "config" / entity_type

    def assets_entity_dir(self, entity_type: str) -> Path:
        """通用实体资产目录（characters / scenes）"""
        return self._root / "assets" / entity_type

    def config_entity_yaml(self, entity_type: str, entity_id: str) -> Path:
        """通用实体配置文件"""
        return self._root / "config" / entity_type / f"{entity_id}.yaml"

    def assets_entity_file(self, entity_type: str, entity_id: str, filename: str) -> Path:
        """通用实体资产文件"""
        return self._root / "assets" / entity_type / entity_id / filename

    def seko_asset_dir(self, task_id: str) -> Path:
        """Seko 策划案资产目录"""
        return self._root / "assets" / "seko" / task_id

    def ensure_dirs(self) -> None:
        """创建所有标准子目录"""
        for d in [
            self.config_dir, self.characters_dir, self.scenes_dir,
            self.storyboard_dir, self.assets_dir,
            self.character_assets_dir, self.scene_assets_dir, self.loras_dir,
            self.output_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


def cfg_get(cfg: dict, dotted_key: str, default=""):
    """从嵌套 dict 中按点分路径取值，如 'models.gpt_sovits.api_url'"""
    parts = dotted_key.split(".")
    cur = cfg
    for p in parts:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


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
            logger.error(f"配置文件 YAML 格式错误: {abspath}: {e}", exc_info=True)
            data = {}
        _cache[abspath] = (data, os.path.getmtime(abspath))
    return copy.deepcopy(data)


def save_yaml(path: str | Path, data: Any, *, sort_keys: bool = False) -> None:
    """原子写入 YAML 文件（temp file + rename，防崩溃损坏）"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=sort_keys)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            logger.debug(f"{type(e).__name__}: {e}")
        raise


def save_config(path: str, data: dict[str, Any]) -> None:
    """保存 YAML 配置（原子写入）"""
    save_yaml(path, data, sort_keys=False)
    abspath = str(Path(path).resolve())
    with _lock:
        _cache[abspath] = (copy.deepcopy(data), os.path.getmtime(abspath))


class Config:
    """统一配置对象 — 聚合 project.yaml + .env + 默认值"""

    # 默认配置（project.name 不设默认值，由 REQUIRED_FIELDS 强制要求）
    # 系统全局配置路径
    SYSTEM_CONFIG = None  # 延迟设置

    DEFAULTS: dict[str, Any] = {
        "project": {"episodes": 1, "fps": 24,
                     "style": "cinematic", "genre": "urban"},
        "comfyui": {"url": "http://127.0.0.1:8188", "api_key": ""},
        # models 和 llm 的默认值来自 models_registry.yaml，不在此硬编码
        "models": {},
        "llm": {"enabled": False, "base_url": "https://api.siliconflow.cn",
                "model": "Qwen/Qwen2.5-7B-Instruct", "api_key": "",
                "batch_translate": True, "context_length": 0},
        "portraits": {"auto_outfit": True},
        "server": {"port": 8888, "host": "0.0.0.0", "cors_origin": "*"},
        "timeouts": {"comfyui": 900, "tts": 60, "lipsync": 120, "llm": 300, "music": 120},
        "post_production": {
            "transition": "crossfade",
            "transition_duration": 0.5,
            "bgm_volume": 0.15,
        },
    }

    # 必填字段校验规则
    REQUIRED_FIELDS: list[tuple[str, str]] = [
        ("project.name", "项目名称"),
    ]

    # 合法值范围
    VALID_RANGES: dict[str, tuple[int, int]] = {
        "project.fps": (1, 120),
        "server.port": (1, 65535),
        "post_production.transition_duration": (0, 10),
        "post_production.bgm_volume": (0, 1),
        "timeouts.comfyui": (1, 7200),
        "timeouts.tts": (1, 600),
        "timeouts.lipsync": (1, 600),
        "timeouts.llm": (1, 3600),
        "timeouts.music": (1, 600),
    }

    def __init__(self, path: str | None = None):
        self._mtimes: dict[str, float] = {}
        self._reloading = False
        self._path = path or self._find_config()
        # 设置系统配置路径（使用模块级常量，避免重复拼接）
        if Config.SYSTEM_CONFIG is None:
            Config.SYSTEM_CONFIG = SYSTEM_CONFIG_PATH
        self._data = self._merge(self._path)
        self._project_dir = str(Path(self._path).resolve().parent.parent) if self._path else os.getcwd()
        # 注入 project_dir 供后端使用（Container._backend_config 依赖此键）
        self._data["_project_dir"] = self._project_dir
        self._warnings: list[str] = []
        self._validate()
        # 记录源文件 mtime，用于热读取检测
        self._record_mtimes()

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
        """合并默认配置 + 注册表默认值 + 系统全局配置 + 项目配置"""
        merged = copy.deepcopy(self.DEFAULTS)
        # 0. 从 models_registry.yaml 读取默认后端名（注册表是唯一真相来源）
        try:
            from flow.model_registry import ModelRegistry
            reg = ModelRegistry(path or str(Path(__file__).resolve().parent.parent / "config" / "project.yaml"))
            reg_defaults = reg.get_defaults()
            if reg_defaults:
                # 注入 models 段的后端默认值（tts_backend, image_backend 等）
                models_defaults = {k: v for k, v in reg_defaults.items()
                                   if k.endswith("_backend") and k != "llm_backend"}
                merged.setdefault("models", {}).update(models_defaults)
                # 注入 llm.backend（llm 段独立于 models）
                if "llm_backend" in reg_defaults:
                    merged.setdefault("llm", {})["backend"] = reg_defaults["llm_backend"]
        except Exception as e:
            logger.debug(f"注册表不可用，使用 DEFAULTS 兜底: {e}")
        # 1. 合并系统全局配置
        sys_path = getattr(Config, 'SYSTEM_CONFIG', None)
        if sys_path and os.path.isfile(sys_path):
            sys_data = load_config(sys_path)
            self._deep_merge(merged, sys_data)
        # 2. 合并项目配置（覆盖系统配置）
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
        self._check_reload()
        return self._data

    @property
    def project_dir(self) -> str:
        return self._project_dir

    @property
    def paths(self) -> ProjectPaths:
        """统一路径管理对象"""
        return ProjectPaths(self._project_dir)

    @property
    def path(self) -> str:
        return self._path or ""

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持 dot notation: 'models.tts_backend'，文件变化时自动重载）"""
        self._check_reload()
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

    def _record_mtimes(self) -> None:
        """记录所有配置源文件的 mtime"""
        paths = []
        sys_path = getattr(Config, 'SYSTEM_CONFIG', None)
        if sys_path and os.path.isfile(sys_path):
            paths.append(sys_path)
        if self._path and os.path.isfile(self._path):
            paths.append(self._path)
        for p in paths:
            try:
                self._mtimes[p] = os.path.getmtime(p)
            except OSError:
                logger.debug(f"{type(e).__name__}: {e}")

    def _check_reload(self) -> bool:
        """检测源文件是否变化，变化则自动重载。返回是否发生了重载。"""
        if self._reloading:
            return False
        changed = False
        for p in list(self._mtimes):
            try:
                mtime = os.path.getmtime(p)
                if mtime != self._mtimes[p]:
                    changed = True
                    break
            except OSError:
                continue
        if changed:
            self.reload()
            return True
        return False

    def reload(self) -> None:
        """重新加载配置"""
        self._reloading = True
        try:
            self._do_reload()
        finally:
            self._reloading = False

    def _do_reload(self) -> None:
        # 清除 load_config 的 mtime 缓存，强制重新读取文件
        for p in (getattr(Config, 'SYSTEM_CONFIG', None), self._path):
            if p:
                abspath = str(Path(p).resolve())
                _cache.pop(abspath, None)
        self._data = self._merge(self._path)
        self._data["_project_dir"] = self._project_dir
        self._warnings = []
        self._validate()
        self._record_mtimes()

    def _get_raw(self, key: str, default=None):
        """内部用：直接读 _data，不触发热重载检查"""
        val = self._data
        for k in key.split("."):
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    def _validate(self) -> None:
        """校验配置合法性 — 必填字段缺失时抛异常，范围超限仅警告"""
        # 必填字段（直接访问 _data，避免触发 _check_reload 递归）
        missing = []
        for field, desc in self.REQUIRED_FIELDS:
            val = self._get_raw(field)
            if val is None or val == "":
                missing.append(f"{desc} ({field})")

        if missing:
            raise ValueError(f"缺少必填配置: {', '.join(missing)}")

        # 数值范围（不阻断，仅警告）
        for field, (lo, hi) in self.VALID_RANGES.items():
            val = self._get_raw(field)
            if val is not None:
                try:
                    v = int(val)
                    if v < lo or v > hi:
                        self._warnings.append(
                            f"配置 {field}={v} 超出范围 [{lo}, {hi}]"
                        )
                except (ValueError, TypeError):
                    self._warnings.append(f"配置 {field} 不是有效数值: {val}")

        if self._warnings:
            for w in self._warnings:
                logger.warning(f"⚠ 配置校验: {w}")

    @property
    def warnings(self) -> list[str]:
        """返回配置校验警告列表"""
        return list(self._warnings)

    def __repr__(self) -> str:
        return f"Config({self._path})"


def resolve_project_config(root: Path | None = None) -> str:
    """统一的项目配置路径解析（CLI 和 Web 共用）

    查找顺序：
    1. .active 文件指向的项目
    2. projects/default/ 回退
    3. 根目录 config/ 兼容旧结构

    Returns:
        配置文件绝对路径
    """
    if root is None:
        root = Path(__file__).resolve().parent.parent

    # 1. 检查 .active 指向的项目
    active_file = root / "projects" / ".active"
    if active_file.exists():
        try:
            d = active_file.read_text().strip()
            if d:
                cfg = Path(d) / "config" / "project.yaml"
                if cfg.exists():
                    return str(cfg)
        except (OSError, ValueError):
            logger.debug(f"{type(e).__name__}: {e}")

    # 2. 回退到默认项目
    cfg = root / "projects" / "default" / "config" / "project.yaml"
    if cfg.exists():
        return str(cfg)

    # 3. 兼容旧结构（根目录 config/）
    cfg = root / "config" / "project.yaml"
    if cfg.exists():
        return str(cfg)

    raise FileNotFoundError("未找到 config/project.yaml，请先初始化默认项目")


def get_active_project_dir(root: Path | None = None) -> Path:
    """获取当前活动项目目录"""
    if root is None:
        root = Path(__file__).resolve().parent.parent

    active_file = root / "projects" / ".active"
    if active_file.exists():
        try:
            d = active_file.read_text().strip()
            if d:
                p = Path(d)
                if p.exists():
                    return p
        except (OSError, ValueError):
            logger.debug(f"{type(e).__name__}: {e}")

    return root / "projects" / "default"
