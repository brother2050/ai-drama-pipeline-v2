"""Seko 后端注册 — 影视策划案功能"""
from __future__ import annotations

import logging
import os

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)


class SekoProposal:
    """Seko 影视策划案后端"""

    def __init__(self, config: dict):
        self._config = config

    @property
    def name(self) -> str:
        return "seko"

    def is_available(self) -> bool:
        """检查 Seko API Key 是否已配置"""
        key = self._config.get("api_key") or os.environ.get("SEKO_API_KEY", "")
        return bool(key)


# 注册到服务注册表
try:
    registry.register(BackendMeta(
        name="seko",
        service_type="seko",
        factory=lambda cfg: SekoProposal(cfg),
        requires_api_key=True,
        api_key_env="SEKO_API_KEY",
        description="Seko 影视策划案（seko.sensetime.com）",
        priority=10,
    ))
except Exception as e:
    logger.debug(f"Seko 后端注册跳过: {e}")
