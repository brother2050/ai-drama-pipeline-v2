"""镜头管理器 — 读取分镜表、构建 prompt、管理状态"""
from __future__ import annotations
import csv, logging, os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ShotManager:
    """镜头管理器"""

    REQUIRED = ("episode", "shot_id", "scene", "characters", "action", "dialogue")

    def __init__(self, storyboard_path: str, config_dir: str, config: dict | None = None):
        self.storyboard_path = storyboard_path
        self.config_dir = config_dir
        self.config = config or {}
        self.shots: list[dict] = []
        self.characters: dict[str, dict] = {}
        self.scenes: dict[str, dict] = {}
        self._load_all()

    def _load_all(self):
        self._load_storyboard()
        self._load_characters()
        self._load_scenes()
        self._resolve_refs()
        logger.info(f"加载: {len(self.characters)} 角色, {len(self.scenes)} 场景, {len(self.shots)} 镜头")

    def _load_storyboard(self):
        if not os.path.exists(self.storyboard_path):
            return
        with open(self.storyboard_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.shots.append(dict(row))
        self.shots.sort(key=lambda s: s.get("shot_id", "000"))

    def _load_characters(self):
        chars_dir = Path(self.config_dir) / "characters"
        if not chars_dir.exists():
            return
        import yaml
        for f in chars_dir.glob("*.yaml"):
            if f.stem.endswith(".example"):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                char = data.get("character", {})
                if char.get("id"):
                    self.characters[char["id"]] = char
            except Exception as e:
                logger.warning(f"加载角色失败 {f}: {e}")

    def _load_scenes(self):
        scenes_dir = Path(self.config_dir) / "scenes"
        if not scenes_dir.exists():
            return
        import yaml
        for f in scenes_dir.glob("*.yaml"):
            if f.stem.endswith(".example"):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                scene = data.get("scene", {})
                if scene.get("id"):
                    self.scenes[scene["id"]] = scene
            except Exception as e:
                logger.warning(f"加载场景失败 {f}: {e}")

    def _resolve_refs(self):
        """解析角色/场景名→ID"""
        name_to_id = {c.get("name", ""): cid for cid, c in self.characters.items()}
        for shot in self.shots:
            chars = shot.get("characters", "")
            if chars and chars not in self.characters:
                # 支持 "+" 分隔的多角色名解析
                parts = [c.strip() for c in chars.split("+")]
                resolved = "+".join(name_to_id.get(p, p) for p in parts)
                shot["characters"] = resolved

    def get_character(self, char_id: str) -> dict:
        return self.characters.get(char_id, {})

    def get_scene(self, scene_id: str) -> dict:
        return self.scenes.get(scene_id, {})

    def get_shots_for_episode(self, episode: int) -> list[dict]:
        result = []
        for s in self.shots:
            try:
                ep = int(s.get("episode", 0) or 0)
            except (ValueError, TypeError):
                continue
            if ep == episode:
                result.append(s)
        return result

    def validate(self) -> list[str]:
        errors = []
        for i, shot in enumerate(self.shots):
            for field in self.REQUIRED:
                if not shot.get(field):
                    errors.append(f"镜头 {i}: 缺少 {field}")
        return errors
