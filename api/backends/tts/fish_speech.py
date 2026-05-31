"""Fish-Speech TTS — HTTP API 轻量语音合成"""
from __future__ import annotations
import logging
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class FishSpeech:
    def __init__(self, config: dict):
        self._url = config.get("api_url", "http://127.0.0.1:8083")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        from infra.http_pool import get_client; self._client = get_client(timeout=self._timeout)
        from infra.http_pool import get_client; self._fast_client = get_client(timeout=3)

    @property
    def name(self): return "fish-speech"

    def synthesize(self, text: str, output: str, *, voice_config: dict | None = None,
                   emotion: str = "neutral", language: str = "zh") -> str:
        voice_config = voice_config or {}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        r = self._client.post(f"{self._url}/v1/tts", json={
            "text": text, "reference_id": voice_config.get("reference_id", ""),
            "format": "wav",
        })
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self):
        try:
            r = self._fast_client.get(f"{self._url}/docs")
            return True, f"Fish-Speech reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"Fish-Speech unreachable: {e}"

    def shutdown(self):
        pass  # 共享连接池，无需关闭
        pass  # 共享连接池

def _f(config): return FishSpeech(config)
registry.register(BackendMeta(name="fish-speech", service_type="tts", factory=_f,
    description="Fish-Speech 轻量 TTS", priority=70, tags=["api"]))
