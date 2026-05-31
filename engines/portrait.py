"""定妆照生成 — 确保角色有参考图（含三视图）"""
from __future__ import annotations

import hashlib
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


def _view_seed(char_id: str, generation: int, view_index: int) -> int:
    """三视图 seed：同角色同代不同视角，不同角色完全隔离

    注意：为保持三视图人物一致性，所有视角使用相同 seed。
    view_index 保留用于未来需要差异化时扩展。
    """
    h = hashlib.md5(f"{char_id}:gen{generation}:portrait".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _outfit_seed(char_id: str, generation: int, outfit_index: int) -> int:
    """服装图 seed：同角色同代不同服装，不同角色完全隔离"""
    h = hashlib.md5(f"{char_id}:gen{generation}:outfit{outfit_index}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _generate_view(char_id: str, appearance: str, portrait_dir: Path,
                   comfyui, wb, filename: str, shot_type: str,
                   seed: int | None = None,
                   ref_image: str | None = None,
                   char: dict | None = None,
                   project_dir: str = "") -> str:
    """生成单张视图，返回文件路径或空字符串

    Args:
        seed: 指定 seed 保持一致性（None 则随机）
        ref_image: IP-Adapter 参考图路径（用于保持角色一致性）
        char: 角色数据 dict（用于读取视角专属描述）
        project_dir: 项目目录全路径（用于生成唯一 ComfyUI 文件名 + AssetTracker）
    """
    # 获取视角专属 prompt（prepare 阶段已生成）
    from engines.prompt import get_view_appearance
    view_desc = get_view_appearance(char, shot_type) if char else ""
    if not view_desc:
        logger.error(f"角色 '{char_id}' 未生成 AI 绘图 prompt，请先运行: drama prepare <episode>")
        return ""

    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": shot_type, "camera": "固定"}
    prompt, wf = wb.build_first_frame(fake_shot, character_desc=view_desc, seed=seed)
    if not wf:
        return ""

    # 注入参考图到 IP-Adapter（保持角色面部/体型一致性）
    if ref_image and os.path.exists(ref_image):
        from engines.workflow import find_character_load_image_nodes
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            from infra.asset_tracker import comfyui_asset_name, AssetTracker
            remote_name = comfyui_asset_name(project_dir, char_id, os.path.basename(ref_image))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name
            try:
                tracker = AssetTracker(project_dir)
                tracker.upload_if_needed(comfyui, ref_image, remote_name, comfyui.url)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    files = comfyui.generate(wf, str(portrait_dir))
    if not files:
        return ""
    # 重命名为目标文件名
    target = portrait_dir / filename
    os.replace(files[0], str(target))
    return str(target)


def ensure_portrait(char_id: str, config: dict, container=None, force: bool = False) -> str:
    """确保角色有定妆照（三视图），没有则生成

    生成三张图：
      - cover.png 正面特写
      - side.png  侧面特写
      - back.png  背面特写

    配置项 portraits.auto_outfit:
      - False（默认）: 只生成三视图，不遍历 outfits
      - True: 同时为各 outfit 生成参考图

    Args:
        force: True 时重新生成（递增代数计数器）
    """
    from infra.config import ProjectPaths
    project_dir = config.get("_project_dir", os.getcwd())
    paths = ProjectPaths(project_dir)
    portrait_dir = paths.character_asset_dir(char_id)

    # 检查三视图是否齐全
    all_views_exist = all((portrait_dir / fname).exists() for fname, *_ in _THREE_VIEWS)
    if all_views_exist:
        auto_outfit = config.get("portraits", {}).get("auto_outfit", False)
        if auto_outfit and container:
            _ensure_outfit_images(char_id, config, container, project_dir, portrait_dir)
        return str(portrait_dir / "cover.png")

    # 重入保护（检查 + 标记必须在同一把锁内，避免间隙导致重复生成）
    with _generating_lock:
        if char_id in _generating:
            logger.warning(f"角色 '{char_id}' 定妆照正在生成中，跳过重入")
            return ""
        _generating.add(char_id)

    logger.info(f"角色 '{char_id}' 缺少三视图，自动生成...")
    import yaml
    char_file = paths.character_yaml(char_id)
    if not char_file.exists():
        logger.warning(f"角色配置不存在: {char_file}")
        return ""

    with open(char_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    char = data.get("character", {})
    appearance = char.get("appearance", char_id)

    if not container:
        return ""

    try:
        comfyui = container.get("image")
        from engines.workflow_builder import WorkflowBuilder
        models = config.get("models", {})
        wb = WorkflowBuilder(config, models, str(paths.root), comfyui=comfyui, force=force)
        wb.load_workflows()

        # 读取代数计数器（force 时递增，得到不同的生成结果）
        generation = char.get("portrait_generation", 0)
        if force:
            generation += 1
            char["portrait_generation"] = generation
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(char_file, data)
            logger.info(f"  🔄 重新生成，代数: {generation}")

        # 确定性 seed：同一角色+同一代 → 所有视图/服装共享基础 seed
        cover_path = portrait_dir / "cover.png"

        generated_urls = []
        for i, (filename, shot_type, camera, label) in enumerate(_THREE_VIEWS):
            if (portrait_dir / filename).exists():
                generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
                continue

            # 每个视角独立 seed（含 char_id + generation + view_index，不同角色完全隔离）
            view_seed = _view_seed(char_id, generation, i)

            # side/back 视图用 cover 做 IP-Adapter 参考（保持角色一致性）
            ref = str(cover_path) if i > 0 and cover_path.exists() else None

            result = _generate_view(char_id, appearance, portrait_dir, comfyui, wb,
                                    filename, shot_type, seed=view_seed, ref_image=ref,
                                    char=char, project_dir=project_dir)
            if result:
                generated_urls.append(f"/api/assets/characters/{char_id}/{filename}")
                logger.info(f"  ✅ {label}视图: {filename} (seed={view_seed})")
            else:
                logger.warning(f"  ⚠ {label}视图生成失败")

        # 回写 reference_images（只保留三视图，移除旧的 cover/side/back）
        if generated_urls:
            char.setdefault("reference_images", [])
            prefix = f"/api/assets/characters/{char_id}/"
            view_filenames = {fn for fn, *_ in _THREE_VIEWS}
            char["reference_images"] = [
                u for u in char["reference_images"]
                if not u.startswith(prefix) or u.rsplit("/", 1)[-1] not in view_filenames
            ]
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
            _ensure_outfit_images(char_id, config, container, project_dir, portrait_dir)

        return str(portrait_dir / "cover.png") if (portrait_dir / "cover.png").exists() else ""

    except Exception as e:
        logger.error(f"定妆照生成失败: {e}")
        return ""
    finally:
        with _generating_lock:
            _generating.discard(char_id)


def _ensure_outfit_images(char_id: str, config: dict, container,
                          project_dir: str, portrait_dir: Path) -> None:
    """为角色的各 outfit 生成参考图（如果尚未存在）

    使用 cover.png 作为 IP-Adapter 参考图，保持角色面部一致性。
    """
    import yaml
    from infra.config import ProjectPaths
    paths = ProjectPaths(project_dir)
    char_file = paths.character_yaml(char_id)
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

    models = config.get("models", {})
    wb = WorkflowBuilder(config, models, str(paths.root), comfyui=comfyui)
    wb.load_workflows()

    # 使用 cover.png 作为所有服装图的 IP-Adapter 参考（保持角色面部一致性）
    cover_path = portrait_dir / "cover.png"
    generation = char.get("portrait_generation", 0)

    # 读取模型友好 prompt（prepare 阶段已生成）
    appearance_en = char.get("appearance_prompt_en", "")
    if not appearance_en:
        logger.error(f"角色 '{char_id}' 未生成 AI 绘图 prompt，请先运行: drama prepare <episode>")
        return

    for outfit_idx, (outfit_key, outfit_val) in enumerate(outfits.items()):
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
        # 服装描述（prepare 阶段已翻译 description_en）
        outfit_desc_en = outfit_val.get("description_en", "")
        if not outfit_desc_en:
            if outfit_desc:
                logger.error(f"角色 '{char_id}' 的服装 '{outfit_key}' 尚未生成英文描述，请先执行: drama prepare <集数>")
            continue
        full_desc = f"{appearance_en}, wearing {outfit_desc_en}"

        # 服装图 seed（含 char_id + generation + outfit_index，不同角色完全隔离）
        outfit_seed = _outfit_seed(char_id, generation, outfit_idx)

        fake_shot = {"characters": char_id, "emotion": "neutral",
                     "shot_type": "全身", "camera": "固定"}
        _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc, seed=outfit_seed)
        if not wf:
            continue

        # 注入 cover 作为 IP-Adapter 参考图
        if cover_path.exists():
            from engines.workflow import find_character_load_image_nodes
            from infra.asset_tracker import comfyui_asset_name, AssetTracker
            char_nodes = find_character_load_image_nodes(wf)
            if char_nodes:
                remote_name = comfyui_asset_name(project_dir, char_id, os.path.basename(str(cover_path)))
                wf[char_nodes[0]]["inputs"]["image"] = remote_name
                try:
                    tracker = AssetTracker(project_dir)
                    tracker.upload_if_needed(comfyui, str(cover_path), remote_name, comfyui.url)
                except Exception as e:
                    logger.warning(f"参考图上传失败: {e}")

        try:
            files = comfyui.generate(wf, str(outfit_dir))
            if files:
                # 重命名为 cover.png
                cover_out = outfit_dir / "cover.png"
                os.replace(files[0], str(cover_out))
                outfit_url = f"/api/assets/characters/{char_id}/{outfit_key}/cover.png"
                outfit_val.setdefault("reference_images", [])
                prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
                outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
                outfit_val["reference_images"].append(outfit_url)
                data["character"] = char
                from infra.config import save_yaml
                save_yaml(char_file, data)
                logger.info(f"  👗 outfit '{outfit_key}' 生成完成 (seed={outfit_seed})")
        except Exception as e:
            logger.warning(f"  ⚠ outfit '{outfit_key}' 生成失败: {e}")
