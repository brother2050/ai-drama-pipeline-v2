"""MiMo VoiceDesign TTS — 云 API，免费，自然语言描述生成声音

API 文档: https://api.xiaomimimo.com
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["MimoVoiceDesign"]


class MimoVoiceDesign:
    """MiMo VoiceDesign TTS 后端（云 API，免费）"""

    API_URL = "https://api.xiaomimimo.com/v1/audio/speech"

    def __init__(self, config: dict):
        self._api_key = config.get("api_key") or os.environ.get("MIMO_API_KEY", "")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._project_dir = config.get("project_dir", "")

    @property
    def name(self) -> str:
        return "mimo-voicedesign"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        """合成语音"""
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置。获取: https://api.xiaomimimo.com")

        voice_config = voice_config or {}
        voice_desc = voice_config.get("voice_description", "中性声音，发音标准清晰")

        Path(output).parent.mkdir(parents=True, exist_ok=True)

        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json={"model": "mimo-voice-design",
                      "input": text,
                      "voice": voice_desc,
                      "language": language,
                      "emotion": emotion},
            )
            r.raise_for_status()

            with open(output, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    f.write(chunk)

        return output

    def health_check(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "MIMO_API_KEY 未设置"
        return True, "API key 已配置"

    def shutdown(self) -> None:
        pass


def _factory(config: dict) -> MimoVoiceDesign:
    return MimoVoiceDesign(config)

registry.register(BackendMeta(
    name="mimo-voicedesign", service_type="tts", factory=_factory,
    requires_api_key=True, api_key_env="MIMO_API_KEY",
    description="MiMo VoiceDesign 云 API（免费）", priority=10, tags=["cloud", "free"],
))
