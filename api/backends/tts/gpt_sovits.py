"""GPT-SoVITS TTS — HTTP API 语音克隆"""

from __future__ import annotations
import logging
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)


class GptSovits:
    def __init__(self, config: dict):
        self._url = config.get("api_url", "http://127.0.0.1:9880")
        self._timeout = config.get("timeouts", {}).get("tts", 60)

    @property
    def name(self) -> str:
        return "gpt-sovits"

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        voice_config = voice_config or {}
        ref_audio = voice_config.get("reference_audio", "")
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self._url}/tts", json={
                "text": text, "text_language": language,
                "refer_audio_path": ref_audio,
                "prompt_text": voice_config.get("prompt_text", ""),
            })
            r.raise_for_status()
            with open(output, "wb") as f:
                f.write(r.content)
        return output

    def health_check(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=3) as c:
                r = c.get(f"{self._url}/docs")
                return True, f"GPT-SoVITS reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"GPT-SoVITS unreachable: {e}"

    def shutdown(self) -> None:
        pass


def _factory(config: dict) -> GptSovits:
    return GptSovits(config)

registry.register(BackendMeta(
    name="gpt-sovits", service_type="tts", factory=_factory,
    description="GPT-SoVITS 语音克隆", priority=50, tags=["api"],
))
