"""MiMo VoiceClone TTS — 云 API，参考音频克隆声音

使用 MiMo TTS API（chat completions 端点），通过参考音频克隆声音。
支持模型: mimo-v2.5-tts-voiceclone, mimo-v2-tts

不同模型的 voice 参数格式不同:
- mimo-v2.5-tts-voiceclone: audio.voice = "data:audio/wav;base64,<b64>" (DataURL)
- mimo-v2-tts: audio.voice_audio = {format: "wav", data: "<b64>"} (嵌套对象)

官方文档: https://platform.xiaomimimo.com/docs/zh-CN/api/chat/openai-api
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


class MimoVoiceClone:
    """MiMo VoiceClone TTS 后端（云 API）"""

    API_URL = os.environ.get("MIMO_API_ENDPOINT", "https://api.xiaomimimo.com/v1/chat/completions")
    MODEL = os.environ.get("MIMO_TTS_CLONE_MODEL", "mimo-v2.5-tts-voiceclone")

    def __init__(self, config: dict):
        self._api_key = config.get("api_key") or os.environ.get("MIMO_API_KEY", "")
        self._timeout = config.get("timeouts", {}).get("tts", 60)

    @property
    def name(self) -> str:
        return "mimo-voiceclone"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        """合成语音（克隆参考音频的声音）

        Args:
            text: 要合成的文本
            output: 输出 WAV 文件路径
            voice_config: 必须包含 reference_audio (参考音频路径)
        """
        if not self._api_key:
            raise RuntimeError("MIMO_API_KEY 未设置")

        voice_config = voice_config or {}
        ref_audio = voice_config.get("reference_audio", "")
        if not ref_audio:
            raise RuntimeError("VoiceClone 需要 reference_audio 配置")

        if not os.path.exists(ref_audio):
            raise RuntimeError(f"参考音频不存在: {ref_audio}")

        Path(output).parent.mkdir(parents=True, exist_ok=True)

        # 读取参考音频并 base64 编码
        with open(ref_audio, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")

        # 构建 audio 参数（根据模型选择不同格式）
        audio_params: dict = {"format": "wav"}
        if "voiceclone" in self.MODEL:
            # mimo-v2.5-tts-voiceclone: voice 为 DataURL 格式
            audio_params["voice"] = f"data:audio/wav;base64,{audio_b64}"
        else:
            # mimo-v2-tts: voice_audio 为嵌套对象
            audio_params["voice_audio"] = {"format": "wav", "data": audio_b64}

        payload = {
            "model": self.MODEL,
            "audio": audio_params,
            "messages": [{"role": "assistant", "content": text}],
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

        # 写入文件
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


def _factory(config: dict) -> MimoVoiceClone:
    return MimoVoiceClone(config)

registry.register(BackendMeta(
    name="mimo-voiceclone", service_type="tts", factory=_factory,
    requires_api_key=True, api_key_env="MIMO_API_KEY",
    description="MiMo VoiceClone 云 API", priority=20, tags=["cloud"],
))
