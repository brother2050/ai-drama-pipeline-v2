"""CosyVoice TTS — HTTP API 多语言语音合成"""
from __future__ import annotations
import logging
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class CosyVoice:
    def __init__(self, config: dict):
        self._url = config.get("api_url", "http://127.0.0.1:8081")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = httpx.Client(timeout=self._timeout)
        self._fast_client = httpx.Client(timeout=3)

    @property
    def name(self): return "cosyvoice"

    def synthesize(self, text: str, output: str, *, voice_config: dict | None = None,
                   emotion: str = "neutral", language: str = "zh") -> str:
        voice_config = voice_config or {}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        r = self._client.post(f"{self._url}/api/tts", json={
            "text": text, "language": language,
            "speaker": voice_config.get("speaker", "default"),
            "emotion": emotion,
        })
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self):
        try:
            r = self._fast_client.get(f"{self._url}/docs")
            return True, f"CosyVoice reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"CosyVoice unreachable: {e}"

    def shutdown(self):
        self._client.close()
        self._fast_client.close()

def _f(config): return CosyVoice(config)
registry.register(BackendMeta(name="cosyvoice", service_type="tts", factory=_f,
    description="CosyVoice 多语言 TTS", priority=60, tags=["api"]))
