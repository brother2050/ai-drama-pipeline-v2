"""MiMo VoiceClone TTS — 云 API，参考音频克隆声音"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)


class MimoVoiceClone:
    """MiMo VoiceClone TTS 后端（云 API）"""

    API_URL = "https://api.xiaomimimo.com/v1/audio/speech"

    def __init__(self, config: dict):
        self._api_key = config.get("api_key") or os.environ.get("MIMO_API_KEY", "")
        self._timeout = config.get("timeouts", {}).get("tts", 60)

    @property
    def name(self) -> str:
        return "mimo-voiceclone"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置")

        voice_config = voice_config or {}
        ref_audio = voice_config.get("reference_audio", "")
        if not ref_audio:
            raise RuntimeError("VoiceClone 需要 reference_audio 配置")

        Path(output).parent.mkdir(parents=True, exist_ok=True)

        with httpx.Client(timeout=self._timeout) as client:
            with open(ref_audio, "rb") as af:
                r = client.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"reference": (Path(ref_audio).name, af, "audio/wav")},
                    data={"model": "mimo-voice-clone", "input": text, "language": language, "emotion": emotion},
                )
            r.raise_for_status()
            with open(output, "wb") as f:
                f.write(r.content)

        return output

    def health_check(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "MIMO_API_KEY 未设置"
        return True, "API key 已配置"

    def shutdown(self) -> None:
        pass


def _factory(config: dict) -> MimoVoiceClone:
    return MimoVoiceClone(config)

registry.register(BackendMeta(
    name="mimo-voiceclone", service_type="tts", factory=_factory,
    requires_api_key=True, api_key_env="MIMO_API_KEY",
    description="MiMo VoiceClone 云 API", priority=20, tags=["cloud"],
))
