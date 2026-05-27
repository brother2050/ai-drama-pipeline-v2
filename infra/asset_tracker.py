"""ComfyUI 服务器资源跟踪 — 基于 PostgreSQL 持久化

通过 comfyui_assets 表记录哪些图片/LoRA 文件已上传到哪些服务器。
项目删除重建时，数据库中 project_dir 对应的记录为空，自动触发重新上传。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AssetTracker:
    """跟踪项目资源在各 ComfyUI 服务器上的存在状态

    数据存储在 PostgreSQL 表 comfyui_assets 中，以 project_dir 隔离。
    项目删除后重建时，数据库中没有该 project_dir 的记录，所有资产
    都会重新上传，不会复用旧项目的残留文件。
    """

    def __init__(self, project_dir: str):
        self._project_dir = project_dir

    # ── 公开接口 ────────────────────────────────────────

    def is_image_tracked(self, server_url: str, filename: str) -> bool:
        """检查图片是否已记录存在于此服务器"""
        return self._check(server_url, "image", filename)

    def mark_image_tracked(self, server_url: str, filename: str) -> None:
        """记录图片已上传到此服务器"""
        self._mark(server_url, "image", filename)

    def is_lora_tracked(self, server_url: str, lora_name: str) -> bool:
        """检查 LoRA 是否已记录存在于此服务器"""
        return self._check(server_url, "lora", lora_name)

    def mark_lora_tracked(self, server_url: str, lora_name: str) -> None:
        """记录 LoRA 已存在于（或已上传到）此服务器"""
        self._mark(server_url, "lora", lora_name)

    def untrack_image(self, server_url: str, filename: str) -> None:
        """移除图片记录（文件被删除时使用）"""
        self._unmark(server_url, "image", filename)

    def untrack_lora(self, server_url: str, lora_name: str) -> None:
        """移除 LoRA 记录（文件被删除时使用）"""
        self._unmark(server_url, "lora", lora_name)

    # ── 内部实现 ────────────────────────────────────────

    def _check(self, server_url: str, asset_type: str, filename: str) -> bool:
        try:
            from infra.database.comfyui_assets import check
            from infra.database.pool import get_pool
            return check(get_pool(), self._project_dir,
                         server_url.rstrip("/"), asset_type, filename)
        except Exception:
            return False

    def _mark(self, server_url: str, asset_type: str, filename: str) -> None:
        try:
            from infra.database.comfyui_assets import mark
            from infra.database.pool import get_pool
            mark(get_pool(), self._project_dir,
                 server_url.rstrip("/"), asset_type, filename)
        except Exception as e:
            logger.debug(f"AssetTracker mark 失败: {e}")

    def _unmark(self, server_url: str, asset_type: str, filename: str) -> None:
        try:
            from infra.database.comfyui_assets import unmark
            from infra.database.pool import get_pool
            unmark(get_pool(), self._project_dir,
                   server_url.rstrip("/"), asset_type, filename)
        except Exception as e:
            logger.debug(f"AssetTracker unmark 失败: {e}")
