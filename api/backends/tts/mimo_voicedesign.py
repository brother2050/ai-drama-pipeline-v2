"""MiMo VoiceDesign TTS — 云 API，免费，自然语言描述生成声音

使用 MiMo TTS API（chat completions 端点）。
支持模型: mimo-v2.5-tts, mimo-v2.5-tts-voicedesign, mimo-v2-tts

官方文档: https://platform.xiaomimimo.com/docs/zh-CN/api/chat/openai-api
"""

from __future__ import annotations

import base64
import io
import logging
import os
import struct
from pathlib import Path

import httpx

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["MimoVoiceDesign"]

# 情绪标签 → 中文风格描述（用于 MiMo TTS user 消息）
_EMOTION_STYLE_MAP = {
    "happy": "开心愉悦的语气",
    "sad": "悲伤低沉的语气",
    "angry": "愤怒生气的语气",
    "worried": "担忧焦虑的语气",
    "surprised": "惊讶意外的语气",
    "smug": "得意傲慢的语气",
    "serious": "严肃认真的语气",
    "calm": "平静从容的语气",
    "determined": "坚定果断的语气",
    "fearful": "害怕恐惧的语气",
    "romantic": "温柔深情的语气",
    "action": "紧张激烈的语气",
    "neutral": "",
}


class MimoVoiceDesign:
    """MiMo VoiceDesign TTS 后端（云 API，免费）"""

    API_URL = os.environ.get("MIMO_API_ENDPOINT", "https://api.xiaomimimo.com/v1/chat/completions")
    MODEL = os.environ.get("MIMO_TTS_MODEL", "mimo-v2.5-tts")

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
        """合成语音

        Args:
            text: 要合成的文本
            output: 输出 WAV 文件路径
            voice_config: 声音配置，支持 voice_description (风格描述) 和 voice_id (音色ID)
            emotion: 情绪（保留参数，通过 voice_description 传递）
            language: 语言（保留参数）
        """
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置。获取: https://api.xiaomimimo.com")

        voice_config = voice_config or {}
        voice_desc = voice_config.get("voice_description", "")
        voice_id = voice_config.get("voice_id", "")

        # 情绪 → 中文风格描述
        emotion_style = _EMOTION_STYLE_MAP.get(emotion, "")

        # 组合风格：voice_description + 情绪
        style_parts = []
        if voice_desc:
            style_parts.append(voice_desc)
        if emotion_style:
            style_parts.append(emotion_style)
        combined_style = "，".join(style_parts) if style_parts else ""

        Path(output).parent.mkdir(parents=True, exist_ok=True)

        # 构建 messages（遵循官方文档格式）
        messages = []

        # voicedesign 模型必须有 user 消息（风格描述）
        # 其他模型可选
        if combined_style:
            messages.append({"role": "user", "content": combined_style})
        elif "voicedesign" in self.MODEL:
            # voicedesign 无风格时用默认描述
            messages.append({"role": "user", "content": "自然流畅的语音"})

        # 合成文本放在 assistant 消息中（官方文档要求）
        messages.append({"role": "assistant", "content": text})

        # 构建 audio 参数
        audio_params: dict = {"format": "wav"}

        # mimo-v2.5-tts 支持 voice 音色预设
        # mimo-v2.5-tts-voicedesign 不支持 voice 字段
        # 根据模型类型决定是否传 voice
        if "voicedesign" not in self.MODEL:
            # 支持的预设: mimo_default, 冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean
            audio_params["voice"] = voice_id or "mimo_default"

        payload = {
            "model": self.MODEL,
            "audio": audio_params,
            "messages": messages,
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
