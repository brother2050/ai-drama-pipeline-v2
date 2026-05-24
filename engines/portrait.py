"""定妆照生成 — 确保角色有参考图"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_portrait(char_id: str, config: dict, container=None) -> str:
    """确保角色有定妆照，没有则生成一张"""
    project_dir = config.get("_project_dir", os.getcwd())
    portrait_dir = Path(project_dir) / "assets" / "characters" / char_id

    # 查找已有定妆照
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        existing = list(portrait_dir.glob(ext))
        if existing:
            return str(existing[0])

    # 生成一张
    logger.info(f"角色 '{char_id}' 无定妆照，自动生成...")
    import yaml
    char_file = Path(project_dir) / "config" / "characters" / f"{char_id}.yaml"
    if not char_file.exists():
        logger.warning(f"角色配置不存在: {char_file}")
        return ""

    with open(char_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    char = data.get("character", {})
    appearance = char.get("appearance", char_id)

    if container:
        try:
            comfyui = container.get("image")
            prompt = f"portrait photo, {appearance}, high quality, detailed face"
            portrait_dir.mkdir(parents=True, exist_ok=True)
            files = comfyui.generate({"prompt": {"positive": prompt}}, str(portrait_dir))
            if files:
                return files[0]
        except Exception as e:
            logger.error(f"定妆照生成失败: {e}")

    return ""
