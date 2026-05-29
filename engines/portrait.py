"""定妆照生成 — 确保角色有参考图（含三视图）"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 重入保护：正在生成中的角色，防止 build_first_frame → _get_character_refs → ensure_portrait 死循环
_generating: set[str] = set()
_generating_lock = threading.Lock()

# 三视图配置：文件名 → (shot_type, camera, 描述)
_THREE_VIEWS = [
    ("cover.png", "特写", "固定", "正面"),
    ("side.png",  "侧面特写", "固定", "侧面"),
    ("back.png",  "背面特写", "固定", "背面"),
]


def _generate_view(char_id: str, appearance: str, portrait_dir: Path,
                   comfyui, wb, filename: str, shot_type: str) -> str:
    """生成单张视图，返回文件路径或空字符串"""
    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": shot_type, "camera": "固定"}
    prompt, wf = wb.build_first_frame(fake_shot, character_desc=appearance)
    if not wf:
        return ""
    files = comfyui.generate(wf, str(portrait_dir))
    if not files:
        return ""
    # 重命名为目标文件名
    target = portrait_dir / filename
    os.replace(files[0], str(target))
    return str(target)


def ensure_portrait(char_id: str, config: dict, container=None, llm=None) -> str:
    """确保角色有定妆照（三视图），没有则生成

    生成三张图：
      - cover.png 正面特写
      - side.png  侧面特写
      - back.png  背面特写

    配置项 portraits.auto_outfit:
      - False（默认）: 只生成三视图，不遍历 outfits
      - True: 同时为各 outfit 生成参考图
    """
    project_dir = config.get("_project_dir", os.getcwd())
    portrait_dir = Path(project_dir) / "assets" / "characters" / char_id

    # 检查三视图是否齐全
    all_views_exist = all((portrait_dir / fname).exists() for fname, *_ in _THREE_VIEWS)
    if all_views_exist:
        auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
        if auto_outfit and container:
            _ensure_outfit_images(char_id, config, container, llm, project_dir, portrait_dir)
        return str(portrait_dir / "cover.png")

    # 重入保护
    with _generating_lock:
        if char_id in _generating:
            logger.warning(f"角色 '{char_id}' 定妆照正在生成中，跳过重入")
            return ""

    logger.info(f"角色 '{char_id}' 缺少三视图，自动生成...")
    import yaml
    char_file = Path(project_dir) / "config" / "characters" / f"{char_id}.yaml"
    if not char_file.exists():
        logger.warning(f"角色配置不存在: {char_file}")
        return ""

    with open(char_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    char = data.get("character", {})
    appearance = char.get("appearance", char_id)

    if not container:
        return ""

    with _generating_lock:
        _generating.add(char_id)
    try:
        comfyui = container.get("image")
        from engines.workflow_builder import WorkflowBuilder
        models = config.get("models", {})
        wb = WorkflowBuilder(config, models, project_dir, comfyui=comfyui, llm=llm)
        wb.load_workflows()

        generated_urls = []
        for filename, shot_type, camera, label in _THREE_VIEWS:
            if (portrait_dir / filename).exists():
                generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
                continue
            result = _generate_view(char_id, appearance, portrait_dir, comfyui, wb, filename, shot_type)
            if result:
                generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
                logger.info(f"  ✅ {label}视图: {filename}")
            else:
                logger.warning(f"  ⚠ {label}视图生成失败")

        # 回写 reference_images
        if generated_urls:
            char.setdefault("reference_images", [])
            prefix = f"/api/assets/characters/{char_id}/"
            char["reference_images"] = [u for u in char["reference_images"]
                                        if not u.startswith(prefix) or any(u.endswith(f"/{fn}") for fn, *_ in _THREE_VIEWS)]
            # 去重后追加
            existing_set = set(char["reference_images"])
            for url in generated_urls:
                if url not in existing_set:
                    char["reference_images"].append(url)
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)

        # outfit 图
        auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
        if auto_outfit:
            _ensure_outfit_images(char_id, config, container, llm, project_dir, portrait_dir)

        return str(portrait_dir / "cover.png") if (portrait_dir / "cover.png").exists() else ""

    except Exception as e:
        logger.error(f"定妆照生成失败: {e}")
        return ""
    finally:
        with _generating_lock:
            _generating.discard(char_id)


def _ensure_outfit_images(char_id: str, config: dict, container, llm,
                          project_dir: str, portrait_dir: Path) -> None:
    """为角色的各 outfit 生成参考图（如果尚未存在）"""
    import yaml
    char_file = Path(project_dir) / "config" / "characters" / f"{char_id}.yaml"
    if not char_file.exists():
        return

    try:
        with open(char_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return

    char = data.get("character", {})
    outfits = char.get("outfits", {})
    if not isinstance(outfits, dict) or not outfits:
        return

    appearance = char.get("appearance", char_id)
    comfyui = container.get("image")

    from engines.workflow_builder import WorkflowBuilder
    from engines.prompt import translate_to_english

    models = config.get("models", {})
    wb = WorkflowBuilder(config, models, project_dir, comfyui=comfyui, llm=None)
    wb.load_workflows()

    for outfit_key, outfit_val in outfits.items():
        if not isinstance(outfit_val, dict):
            continue
        outfit_desc = outfit_val.get("description", "")
        if not outfit_desc:
            continue

        outfit_dir = portrait_dir / outfit_key
        if outfit_dir.exists():
            existing = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))
            if existing:
                continue

        outfit_dir.mkdir(parents=True, exist_ok=True)
        full_desc = f"{appearance}, wearing {outfit_desc}"
        if any(ord(c) > 127 for c in full_desc):
            full_desc = translate_to_english(full_desc, llm=None)

        fake_shot = {"characters": "", "emotion": "neutral",
                     "shot_type": "全身", "camera": "固定"}
        _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc)
        if not wf:
            continue

        try:
            files = comfyui.generate(wf, str(outfit_dir))
            if files:
                # 重命名为 cover.png
                cover_path = outfit_dir / "cover.png"
                os.replace(files[0], str(cover_path))
                outfit_url = f"/api/assets/characters/{char_id}/{outfit_key}/cover.png"
                outfit_val.setdefault("reference_images", [])
                prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
                outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
                outfit_val["reference_images"].append(outfit_url)
                data["character"] = char
                from infra.config import save_yaml
                save_yaml(char_file, data)
                logger.info(f"  👗 outfit '{outfit_key}' 生成完成")
        except Exception as e:
            logger.warning(f"  ⚠ outfit '{outfit_key}' 生成失败: {e}")
