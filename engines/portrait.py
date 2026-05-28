"""定妆照生成 — 确保角色有参考图"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 重入保护：正在生成中的角色，防止 build_first_frame → _get_character_refs → ensure_portrait 死循环
_generating: set[str] = set()
_generating_lock = threading.Lock()


def ensure_portrait(char_id: str, config: dict, container=None, llm=None) -> str:
    """确保角色有定妆照，没有则生成一张

    配置项 portraits.auto_outfit:
      - False（默认）: 只生成主图，不遍历 outfits，避免阻塞管线
      - True: 同时为各 outfit 生成参考图（会增加耗时）
    """
    project_dir = config.get("_project_dir", os.getcwd())
    portrait_dir = Path(project_dir) / "assets" / "characters" / char_id

    # 查找已有定妆照
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        existing = list(portrait_dir.glob(ext))
        if existing:
            # 主图已存在，检查是否需要补充 outfit 图
            auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
            if auto_outfit and container:
                _ensure_outfit_images(char_id, config, container, llm, project_dir, portrait_dir)
            return str(existing[0])

    # 重入保护：如果该角色正在生成中，直接返回空，避免递归死循环
    with _generating_lock:
        if char_id in _generating:
            logger.warning(f"角色 '{char_id}' 定妆照正在生成中，跳过重入")
            return ""

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
        with _generating_lock:
            _generating.add(char_id)
        try:
            comfyui = container.get("image")
            from engines.workflow_builder import WorkflowBuilder
            models = config.get("models", {})
            wb = WorkflowBuilder(config, models, project_dir, comfyui=comfyui, llm=llm)
            wb.load_workflows()
            fake_shot = {"characters": char_id, "emotion": "neutral",
                         "shot_type": "特写", "camera": "固定"}
            prompt, wf = wb.build_first_frame(fake_shot, character_desc=appearance)
            if wf:
                files = comfyui.generate(wf, str(portrait_dir))
                if files:
                    # 回写 reference_images 到 YAML
                    img_url = f"/api/assets/characters/{char_id}/{Path(files[0]).name}"
                    char.setdefault("reference_images", [])
                    prefix = f"/api/assets/characters/{char_id}/cover"
                    char["reference_images"] = [u for u in char["reference_images"] if not u.startswith(prefix)]
                    char["reference_images"].append(img_url)
                    data["character"] = char
                    from infra.config import save_yaml
                    save_yaml(char_file, data)
                    logger.info(f"已更新角色 YAML: {img_url}")

                    # 主图已落盘，检查是否需要同时生成 outfit 图
                    auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
                    if auto_outfit:
                        _ensure_outfit_images(char_id, config, container, llm, project_dir, portrait_dir)

                    return files[0]
        except Exception as e:
            logger.error(f"定妆照生成失败: {e}")
        finally:
            with _generating_lock:
                _generating.discard(char_id)

    return ""


def _ensure_outfit_images(char_id: str, config: dict, container, llm,
                          project_dir: str, portrait_dir: Path) -> None:
    """为角色的各 outfit 生成参考图（如果尚未存在）

    仅在 portraits.auto_outfit=True 时由 ensure_portrait 调用。
    跳过已有图片的 outfit，不会重复生成。

    注意：此函数内部不使用 build_first_frame 的 IP-Adapter 注入逻辑，
    避免 _get_character_refs → ensure_portrait 的重入死循环。
    直接构建简单工作流，将 outfit 描述拼入 character_desc。
    """
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
        # 跳过已有图片的 outfit
        if outfit_dir.exists():
            existing = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))
            if existing:
                continue

        outfit_dir.mkdir(parents=True, exist_ok=True)
        full_desc = f"{appearance}, wearing {outfit_desc}"
        if any(ord(c) > 127 for c in full_desc):
            full_desc = translate_to_english(full_desc, llm=None)

        # 构建简单工作流（不注入 IP-Adapter，避免重入 ensure_portrait）
        # outfit 描述已拼入 character_desc，直接作为正向 prompt
        fake_shot = {"characters": "", "emotion": "neutral",
                     "shot_type": "全身", "camera": "固定"}
        _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc)
        if not wf:
            continue

        try:
            files = comfyui.generate(wf, str(outfit_dir))
            if files:
                outfit_url = f"/api/assets/characters/{char_id}/{outfit_key}/{Path(files[0]).name}"
                outfit_val.setdefault("reference_images", [])
                prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
                outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
                outfit_val["reference_images"].append(outfit_url)
                # 写回 YAML
                data["character"] = char
                from infra.config import save_yaml
                save_yaml(char_file, data)
                logger.info(f"  👗 outfit '{outfit_key}' 生成完成")
        except Exception as e:
            logger.warning(f"  ⚠ outfit '{outfit_key}' 生成失败: {e}")
