"""MiMo VoiceDesign TTS — 云 API，免费，自然语言描述生成声音

使用 MiMo TTS API（chat completions 端点）。
支持模型: mimo-v2.5-tts, mimo-v2.5-tts-voicedesign, mimo-v2-tts

风格控制方式（根据模型不同）:
- mimo-v2.5-tts / voicedesign: 自然语言描述放在 user 消息（导演模式）
- mimo-v2-tts: <style>标签</style> 放在 assistant 消息开头

官方文档:
- V2.5: https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis-v2.5
- V2: https://platform.xiaomimimo.com/docs/zh-CN/usage-guide/speech-synthesis
"""

from __future__ import annotations

import base64
import logging
import os
import struct
from pathlib import Path

import httpx

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["MimoVoiceDesign"]

# 情绪标签 → V2.5 自然语言风格描述（导演模式，放在 user 消息）
_EMOTION_STYLE_V25 = {
    "happy": "用开心愉悦的语调，声音明亮有活力，语速稍快",
    "sad": "用悲伤低沉的语调，声音压抑，语速缓慢",
    "angry": "用愤怒生气的语调，声音有力，语速稍快",
    "worried": "用担忧焦虑的语调，声音紧张不安",
    "surprised": "用惊讶意外的语调，声音高扬",
    "smug": "用得意傲慢的语调，带着自信",
    "serious": "用严肃认真的语调，声音沉稳有力",
    "calm": "用平静从容的语调，声音温和自然",
    "determined": "用坚定果断的语调，声音有力",
    "fearful": "用害怕恐惧的语调，声音颤抖紧张",
    "romantic": "用温柔深情的语调，声音柔和细腻",
    "action": "用紧张激烈的语调，声音充满张力",
    "neutral": "",
}

# 情绪标签 → V2 风格标签（放在 assistant 消息文本开头 <style>标签</style>）
_EMOTION_STYLE_V2 = {
    "happy": "开心",
    "sad": "悲伤",
    "angry": "生气",
    "worried": "担忧",
    "surprised": "惊讶",
    "smug": "得意",
    "serious": "严肃",
    "calm": "平静",
    "determined": "坚定",
    "fearful": "恐惧",
    "romantic": "温柔",
    "action": "紧张",
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
            emotion: 情绪标签 (happy/sad/angry/worried/surprised/smug/serious/calm/determined/fearful/romantic/action/neutral)
            language: 语言（保留参数）
        """
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置。获取: https://api.xiaomimimo.com")

        voice_config = voice_config or {}
        voice_desc = voice_config.get("voice_description", "")
        voice_id = voice_config.get("voice_id", "")

        is_v25 = "v2.5" in self.MODEL or "voicedesign" in self.MODEL
        is_voicedesign = "voicedesign" in self.MODEL

        Path(output).parent.mkdir(parents=True, exist_ok=True)

        messages = []
        synthesis_text = text

        if is_v25:
            # ── V2.5 系列: 自然语言风格放在 user 消息 ──
            emotion_desc = _EMOTION_STYLE_V25.get(emotion, "")
            style_parts = []
            if voice_desc:
                style_parts.append(voice_desc)
            if emotion_desc:
                style_parts.append(emotion_desc)
            combined_style = "，".join(style_parts) if style_parts else ""

            if combined_style:
                messages.append({"role": "user", "content": combined_style})
            elif is_voicedesign:
                # voicedesign 必须有 user 消息
                messages.append({"role": "user", "content": "自然流畅的语音"})

            messages.append({"role": "assistant", "content": synthesis_text})
        else:
            # ── V2 系列: <style>标签</style> 放在 assistant 消息开头 ──
            emotion_tag = _EMOTION_STYLE_V2.get(emotion, "")
            if emotion_tag:
                synthesis_text = f"<style>{emotion_tag}</style>{text}"

            if voice_desc:
                # V2 的 user 消息可选，传入对话上下文
                messages.append({"role": "user", "content": voice_desc})

            messages.append({"role": "assistant", "content": synthesis_text})

        # 构建 audio 参数
        audio_params: dict = {"format": "wav"}
        if not is_voicedesign:
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

        if resp.get("error"):
            raise RuntimeError(f"MiMo TTS API 错误: {resp['error']}")

        try:
            audio_data = resp["choices"][0]["message"]["audio"]["data"]
            raw = base64.b64decode(audio_data)
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"MiMo TTS 响应格式异常: {e}") from e

        with open(output, "wb") as f:
            if raw[:4] == b"RIFF":
                f.write(raw)
            else:
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
