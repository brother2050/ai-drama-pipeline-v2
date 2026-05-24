"""定妆照辅助 — 确保角色有参考图

.. deprecated::
    本模块功能与 engines/portrait.py 重叠。
    建议直接使用 engines.portrait.ensure_portrait()。
    保留本模块仅为向后兼容。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_reference_images(char_id: str, shot_manager, project_dir: str) -> list[str]:
    """确保角色有参考图，没有则自动生成

    Args:
        char_id: 角色 ID
        shot_manager: ShotManager 实例
        project_dir: 项目根目录

    Returns:
        参考图路径列表

    .. deprecated::
        请使用 engines.portrait.ensure_portrait() 替代。
    """
    logger.warning(
        f"[{char_id}] ensure_reference_images() 已废弃，"
        "请使用 engines.portrait.ensure_portrait()"
    )

    char_cfg = shot_manager.get_character(char_id)
    refs = char_cfg.get("reference_images", [])

    # 解析相对路径
    resolved = []
    for r in refs:
        if not r:
            continue
        abs_r = os.path.join(project_dir, r) if not os.path.isabs(r) else r
        if os.path.exists(abs_r):
            resolved.append(abs_r)

    if resolved:
        return resolved

    # 查找 assets 目录
    char_dir = Path(project_dir) / "assets" / "characters" / char_id
    if char_dir.exists():
        for ext in ("*.png", "*.jpg", "*.jpeg"):
            resolved.extend(str(p) for p in char_dir.glob(ext))

    if resolved:
        return sorted(resolved)

    # 查找 shared_assets
    shared_dir = Path(project_dir) / "shared_assets" / "characters" / char_id
    if shared_dir.exists():
        for ext in ("*.png", "*.jpg", "*.jpeg"):
            resolved.extend(str(p) for p in shared_dir.glob(ext))

    if resolved:
        return sorted(resolved)

    # 委托给 engines.portrait
    logger.info(f"[{char_id}] 无参考图，委托给 engines.portrait...")
    try:
        from engines.portrait import ensure_portrait
        portrait = ensure_portrait(char_id, {"_project_dir": project_dir}, None)
        if portrait:
            return [portrait]
    except Exception as e:
        logger.error(f"[{char_id}] 定妆照生成失败: {e}")

    return []
