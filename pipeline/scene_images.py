"""场景参考图生成 — 为所有场景生成参考图（共享逻辑）

被以下入口调用：
- scene_images_task（批量，Celery）
- scene_image_single_task（单场景，Celery）
- ai_prepare_task step 5（准备阶段，Celery）
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 进度回调类型: (current, total, message)
ProgressCB = Callable[[int, int, str], None] | None


def _noop_progress(current: int, total: int, msg: str) -> None:
    pass


def run_scene_images(
    config_path: str,
    *,
    force: bool = False,
    scene_ids: list[str] | None = None,
    progress_cb: ProgressCB = None,
) -> dict:
    """生成场景参考图

    Args:
        config_path: 项目配置文件路径
        force: True 时删除已有图片重新生成
        scene_ids: None=全部场景, list=只处理指定场景
        progress_cb: 进度回调 callable(current, total, message)

    Returns:
        {"status": "done", "generated": N, "total": N, "skipped": N}
    """
    import yaml
    from engines.workflow_builder import WorkflowBuilder
    from infra.config import Config, save_yaml
    from api import _ensure_registered
    from api.registry import Container

    _ensure_registered()
    cfg = Config(config_path)
    project_dir = Path(cfg.project_dir)
    cb = progress_cb or _noop_progress

    # 初始化 ComfyUI
    try:
        cont = Container(cfg.data)
        comfyui = cont.get("image")
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 不可用: {e}"}

    # 加载场景文件
    scenes_dir = project_dir / "config" / "scenes"
    if not scenes_dir.exists():
        return {"status": "error", "reason": "场景配置目录不存在"}

    if scene_ids is not None:
        # 单场景模式：只处理指定的场景
        scene_files = []
        for sid in scene_ids:
            p = scenes_dir / f"{sid}.yaml"
            if p.exists():
                scene_files.append(p)
    else:
        scene_files = [f for f in scenes_dir.glob("*.yaml") if not f.stem.endswith(".example")]

    if not scene_files:
        return {"status": "error", "reason": "没有场景配置"}

    models = cfg.get("models", {})
    wb = WorkflowBuilder(cfg.data, models, str(project_dir), comfyui=comfyui)
    wb.load_workflows()

    generated = 0
    skipped = 0
    total = len(scene_files)

    for i, f in enumerate(scene_files):
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except yaml.YAMLError as e:
            logger.warning(f"场景 YAML 格式错误 {f}: {e}")
            continue

        scene = data.get("scene", {})
        sid = scene.get("id", f.stem)
        sname = scene.get("name", sid)
        description = scene.get("description", "")

        cb(i + 1, total, sname)

        # 检查已有图
        scene_asset_dir = project_dir / "assets" / "scenes" / sid
        if scene_asset_dir.exists():
            existing = list(scene_asset_dir.glob("*.png")) + list(scene_asset_dir.glob("*.jpg"))
            if existing:
                if force:
                    for img in existing:
                        img.unlink()
                    logger.info(f"  场景 {sname} 已有 {len(existing)} 张图，已删除（强制模式）")
                else:
                    logger.info(f"  场景 {sname} 已有 {len(existing)} 张图，跳过")
                    skipped += 1
                    continue

        scene_asset_dir.mkdir(parents=True, exist_ok=True)

        # 翻译策略：优先读预翻译的 description_en，缺失时提示用户执行 prepare
        desc_en = scene.get("description_en", "")
        if not desc_en:
            if description and any(ord(c) > 127 for c in description):
                logger.warning(f"  ⚠ 场景 {sname}: 尚未生成英文描述，请先执行: drama prepare <集数>")
                continue
            else:
                desc_en = description

        if not desc_en:
            logger.warning(f"  ⚠ 场景 {sname}: 描述为空，跳过")
            continue

        fake_shot = {"characters": "", "emotion": "neutral",
                     "shot_type": "全景", "camera": "固定"}
        _, wf = wb.build_first_frame(fake_shot, scene_desc=desc_en)
        if not wf:
            logger.warning(f"  ⚠ 场景 {sname}: 工作流为空")
            continue

        try:
            files = comfyui.generate(wf, str(scene_asset_dir))
            if files:
                # 重命名为 cover.png（避免 ComfyUI 原始文件名如 Cosmos__00039_.png 导致 404）
                cover_path = scene_asset_dir / "cover.png"
                os.replace(files[0], str(cover_path))
                img_url = f"/api/assets/scenes/{sid}/cover.png"
                scene.setdefault("reference_images", [])
                prefix = f"/api/assets/scenes/{sid}/cover"
                scene["reference_images"] = [u for u in scene["reference_images"] if not u.startswith(prefix)]
                scene["reference_images"].append(img_url)
                data["scene"] = scene
                save_yaml(f, data)

                # 同步数据库
                try:
                    from infra.database.scenes import upsert as db_up
                    from infra.database.pool import get_pool
                    db_up(get_pool(), sid, scene)
                except Exception as e:
                    logger.debug(f"DB 写入跳过: {e}")

                generated += 1
                logger.info(f"  ✅ 场景 {sname}: 生成完成")
            else:
                logger.warning(f"  ⚠ 场景 {sname}: ComfyUI 未返回图片")
        except Exception as e:
            logger.error(f"  ❌ 场景 {sname}: {e}")

    return {"status": "done", "generated": generated, "total": total, "skipped": skipped}
