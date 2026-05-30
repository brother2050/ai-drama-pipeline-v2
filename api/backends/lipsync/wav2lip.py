"""Wav2Lip 口型同步 — HTTP API"""
from __future__ import annotations
import logging
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class Wav2Lip:
    def __init__(self, config: dict):
        self._url = config.get("api_url", "http://127.0.0.1:8084")
        self._timeout = config.get("timeouts", {}).get("lipsync", 120)
        self._client = httpx.Client(timeout=self._timeout)
        self._fast_client = httpx.Client(timeout=3)

    @property
    def name(self): return "wav2lip"

    def sync(self, video: str, audio: str, output: str) -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(video, "rb") as vf, open(audio, "rb") as af:
            r = self._client.post(f"{self._url}/process",
                       files={"face": vf, "audio": af})
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self):
        try:
            r = self._fast_client.get(self._url)
            return True, f"Wav2Lip reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"Wav2Lip unreachable: {e}"

    def shutdown(self):
        self._client.close()
        self._fast_client.close()

def _f(config): return Wav2Lip(config)
registry.register(BackendMeta(name="wav2lip", service_type="lipsync", factory=_f,
    description="Wav2Lip 口型同步", priority=80, tags=["api"]))
