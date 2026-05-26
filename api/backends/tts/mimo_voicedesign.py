"""MiMo VoiceDesign TTS — 云 API，免费，自然语言描述生成声音

使用 MiMo TTS API（chat completions 端点）。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import struct
from pathlib import Path

import httpx

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["MimoVoiceDesign"]


class MimoVoiceDesign:
    """MiMo VoiceDesign TTS 后端（云 API，免费）"""

    API_URL = "https://api.xiaomimimo.com/v1/chat/completions"
    MODEL = "mimo-v2-audio-tts"

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
        voice_desc = voice_config.get("voice_description", "")

        # 构建 content：style 描述 + 文本
        if voice_desc:
            content = f"<style>{voice_desc}</style>{text}"
        else:
            content = text

        Path(output).parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self.MODEL,
            "audio": {"format": "wav", "voice": "mimo_default"},
            "messages": [{"role": "assistant", "content": content}],
        }

        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                self.API_URL,
                headers={"api-key": self._api_key,
                         "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            resp = r.json()

        # 检查 API 错误
        if resp.get("error"):
            raise RuntimeError(f"MiMo TTS API 错误: {resp['error']}")

        # 解码音频数据
        try:
            audio_data = resp["choices"][0]["message"]["audio"]["data"]
            raw = base64.b64decode(audio_data)
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"MiMo TTS 响应格式异常: {e}") from e

        # 写入文件（自动检测是否需要 WAV 头）
        with open(output, "wb") as f:
            if raw[:4] == b"RIFF":
                f.write(raw)
            else:
                # 包装为 WAV: 24kHz, 16-bit, mono
                sr, bps, ch = 24000, 16, 1
                br = sr * ch * bps // 8
                f.write(b"RIFF")
                f.write(struct.pack("<I", 36 + len(raw)))
                f.write(b"WAVEfmt ")
                f.write(struct.pack("<IHHIIHH", 16, 1, ch, sr, br, ch * bps // 8, bps))
                f.write(b"data")
                f.write(struct.pack("<I", len(raw)))
                f.write(raw)

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
