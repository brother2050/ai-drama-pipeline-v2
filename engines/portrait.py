"""定妆照生成 — 为角色生成多角度参考图"""
from __future__ import annotations
import logging, os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_portraits(config: dict, container=None) -> dict[str, list[str]]:
    """为所有角色生成定妆照"""
    project_dir = config.get("_project_dir", os.getcwd())
    chars_dir = Path(project_dir) / "config" / "characters"
    if not chars_dir.exists():
        logger.warning("角色配置目录不存在")
        return {}

    results = {}
    for f in chars_dir.glob("*.yaml"):
        if f.suffix == ".yaml" and not f.stem.endswith(".example"):
            import yaml
            with open(f) as fh:
                data = yaml.safe_load(fh) or {}
            char = data.get("character", {})
            char_id = char.get("id", f.stem)
            logger.info(f"生成定妆照: {char_id} ({char.get('name', '')})")

            portrait_dir = Path(project_dir) / "assets" / "characters" / char_id
            portrait_dir.mkdir(parents=True, exist_ok=True)

            # 构建 prompt
            appearance = char.get("appearance", "")
            outfits = char.get("outfits", {})
            outfit_desc = list(outfits.values())[0] if outfits else ""
            prompt = f"portrait photo, {appearance}, {outfit_desc}, high quality, detailed face"

            if container:
                try:
                    comfyui = container.get("image")
                    files = comfyui.generate(
                        {"prompt": {"positive": prompt}},
                        str(portrait_dir))
                    results[char_id] = files
                    logger.info(f"  ✅ {char_id}: {len(files)} 张")
                except Exception as e:
                    logger.error(f"  ❌ {char_id}: {e}")
                    results[char_id] = []
            else:
                logger.warning("  无 ComfyUI 连接，跳过")

    return results


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

    with open(char_file) as f:
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
